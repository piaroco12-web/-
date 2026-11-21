"""Render Claude's approved Markdown and publish only a verified four-page DOCX."""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from week import ROOT, publication_week

AREAS = ("AI 활용 역량", "교육전문직 준비", "SW교육체험센터 업무", "AI 활용 방식")


def render(week):
    folder = ROOT / "weekly" / "reports"
    stem = f"{week}_주간분석"
    source = folder / f"{stem}.md"
    template = ROOT / "weekly" / "templates" / "weekly-report.docx"
    if not source.is_file():
        raise ValueError(f"Claude 확정 원고 필요: {source}")
    with tempfile.TemporaryDirectory(dir=folder) as work:
        temp = Path(work)
        draft = temp / f"{stem}.docx"
        subprocess.run(["pandoc", str(source), "--from=markdown", "--to=docx",
                        f"--reference-doc={template}", "-o", str(draft)], check=True)
        doc = Document(draft)
        headers = [p for p in doc.paragraphs if p.style.name == "Heading 2"]
        if tuple(p.text.strip() for p in headers) != AREAS:
            raise ValueError("원고의 ## 영역과 순서 확인 필요: " + " / ".join(AREAS))
        for index, p in enumerate(headers):
            p.paragraph_format.page_break_before = bool(index)
            content = []
            for block in p._p.itersiblings():
                style = block.find(f"{qn('w:pPr')}/{qn('w:pStyle')}")
                if style is not None and style.get(qn("w:val")) == p.style.style_id:
                    break
                content.extend(node.text or "" for node in block.iter(qn("w:t")))
            if not "".join(content).strip():
                raise ValueError(f"빈 영역: {AREAS[index]}")
        doc.core_properties.title = f"{week} 주간 AI 활용 분석"
        doc.save(draft)
        subprocess.run(["soffice", f"-env:UserInstallation={(temp/'profile').as_uri()}",
                        "--headless", "--convert-to", "pdf", "--outdir", str(temp),
                        str(draft)], capture_output=True, check=True)
        pdf = draft.with_suffix(".pdf")
        pages = subprocess.check_output(["pdftotext", "-enc", "UTF-8", "-layout",
                                         str(pdf), "-"], encoding="utf-8").split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        positions = []
        for area in AREAS:
            needle = re.sub(r"\s+", "", area)
            positions.append(next((i + 1 for i, page in enumerate(pages) if any(
                re.sub(r"\s+", "", line) == needle for line in page.splitlines())), None))
        if positions != [1, 2, 3, 4] or len(pages) != 4:
            locations = ", ".join(f"{name}={page or '확인 필요'}쪽"
                                  for name, page in zip(AREAS, positions))
            raise ValueError(f"분량·제목 확인 필요: 총 {len(pages)}쪽, {locations}")
        os.replace(draft, folder / draft.name)
        print(folder / draft.name)


if __name__ == "__main__":
    try:
        render(publication_week())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
