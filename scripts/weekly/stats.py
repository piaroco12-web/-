"""Count GitHub repository activity and Muse's attributed Notion work rows."""
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date, datetime
from urllib.parse import urlparse

from week import KST, ROOT, interval, publication_week

REPO = "piaroco12-web/-"


def run(*args):
    return subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8",
                          capture_output=True, check=True).stdout


def commits(start, end):
    origin = run("git", "remote", "get-url", "origin").strip().removesuffix(".git")
    if origin not in {f"https://github.com/{REPO}", f"git@github.com:{REPO}",
                      f"ssh://git@github.com/{REPO}"}:
        raise ValueError("origin 저장소 확인 필요")
    fetch = ["git", "fetch", "--prune", "--no-tags"]
    if run("git", "rev-parse", "--is-shallow-repository").strip() == "true":
        fetch.append("--unshallow")
    run(*fetch, "origin", "+refs/heads/*:refs/remotes/origin/*")
    lines = run("git", "log", "--remotes=origin", "--format=%ct %H").splitlines()
    ids = set()
    for line in lines:
        timestamp, sha = line.split()
        if start.timestamp() <= int(timestamp) < end.timestamp():
            ids.add(sha)
    return {"count": len(ids), "ids": sorted(ids)}


def prs(start, end):
    lines = run("gh", "api", "--paginate", f"repos/{REPO}/pulls?state=all&per_page=100",
                "--jq", '.[] | [.number, .created_at] | @tsv').splitlines()
    ids = set()
    for line in lines:
        number, created = line.split("\t")
        if start <= datetime.fromisoformat(created.replace("Z", "+00:00")) < end:
            ids.add(int(number))
    return {"count": len(ids), "ids": sorted(ids)}


def notion(path, start, end):
    # A small TSV appendix distinguishes an explicitly empty export from missing data.
    source = path.read_text(encoding="utf-8-sig")
    blocks = re.findall(r"^\x60{3}notion-tsv[ \t]*\n(.*?)^\x60{3}[ \t]*$", source, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError("notion.md의 notion-tsv 원본 행 표 확인 필요")
    rows = csv.DictReader(blocks[0].splitlines(), delimiter="\t")
    if rows.fieldnames != ["날짜", "도구", "유형", "원본"]:
        raise ValueError("notion-tsv 열 확인 필요")
    seen = {}
    for row in rows:
        day = date.fromisoformat(row["날짜"])
        if not start.date() <= day < end.date():
            continue
        ai, kind, source_id = (row[k].strip() for k in ("도구", "유형", "원본"))
        path_part = urlparse(source_id).path.rstrip("/").split("/")[-1].replace("-", "")
        match = re.search(r"([a-fA-F0-9]{32})$", path_part)
        if None in row or not ai or not kind or not match:
            raise ValueError("도구·유형·노션 원본 ID 확인 필요")
        key = match.group(1).lower()
        value = (day.isoformat(), ai, kind)
        if key in seen and seen[key] != value:
            raise ValueError(f"동일 원본의 속성이 다름: {key}")
        seen[key] = value
    counts = Counter(ai for _, ai, kind in seen.values() if kind != "요청")
    requests = sum(kind == "요청" for _, _, kind in seen.values())
    return {"count": sum(counts.values()), "by_ai": dict(sorted(counts.items())),
            "requests": requests, "rows": dict(sorted(seen.items()))}


def measure(function, *args):
    try:
        return {"status": "ok", **function(*args)}
    except (OSError, ValueError, TypeError, AttributeError, subprocess.CalledProcessError) as error:
        reason = type(error).__name__ if isinstance(error, subprocess.CalledProcessError) else str(error)
        return {"status": "확인 필요", "count": None, "reason": reason}


def main():
    week = publication_week()
    start, end = interval(week)
    folder = ROOT / "weekly" / "logs" / week
    folder.mkdir(parents=True, exist_ok=True)
    report = {"week": week, "repository": REPO, "from": start.isoformat(),
              "until_exclusive": end.isoformat(), "queried_at": datetime.now(KST).isoformat(),
              "commits": measure(commits, start, end), "prs": measure(prs, start, end),
              "notion": measure(notion, folder / "notion.md", start, end)}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write("\n")
    os.replace(out.name, folder / "stats.json")
    for key in ("commits", "prs", "notion"):
        print(f"{key}: {report[key]['status']} ({report[key]['count']})")
    return 2 if any(report[k]["count"] is None for k in ("commits", "prs", "notion")) else 0


if __name__ == "__main__":
    sys.exit(main())
