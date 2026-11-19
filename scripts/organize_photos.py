"""현장 사진을 정리하고 번호를 부여함.

설치: python -m pip install Pillow pillow-heif
실행: python scripts/organize_photos.py [방문 폴더]
EXIF에 시간대가 없으면 한국 현지 시각으로 해석함. 실행 환경은 Linux/macOS임.
"""

import argparse
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
import fcntl
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile, gettempdir
from urllib.parse import quote, unquote

from PIL import Image, ImageOps


DEFAULT_VISIT = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "2026-11-19_인천송도_채드윅국제학교-제물포AI센터"
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic"}
KST = timezone(timedelta(hours=9))
INDEX_HEADER = (
    "# 사진 목록\n\n"
    "| 번호 | 파일 | 촬영 시각 | 장소 | 설명 | 보고서 사용 |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
)
SOURCE_ROW = re.compile(
    r"^\| P\d+ \| \[[^\]]+\]\(([^)]+)\) "
    r"<!-- inbox-key:([0-9a-f]{64}) --> \|",
    re.MULTILINE,
)
PHOTO_NUMBER = re.compile(r"^\|\s*P(\d+)\s*\|", re.MULTILINE)
MINUTE_SLOT = re.compile(r"^(\d{4})(?:-(\d+))?_.*\.jpg$")
UNKNOWN_FILE = re.compile(r"^_시각미상/사진\d+\.jpg$")


def capture_time(source: Path) -> datetime | None:
    with Image.open(source) as image:
        exif = image.getexif()
        details = exif.get_ifd(34665)  # Exif IFD
        original = details.get(36867) or exif.get(36867)  # DateTimeOriginal
        offset = details.get(36881) or exif.get(36881)  # OffsetTimeOriginal
    try:
        captured = datetime.strptime(original, "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    if offset:
        try:
            return datetime.strptime(original + offset, "%Y:%m:%d %H:%M:%S%z").astimezone(KST)
        except (TypeError, ValueError, OverflowError):
            pass
    return captured.replace(tzinfo=KST)


def location_at(captured: datetime) -> str:
    minute = captured.time().replace(second=0, microsecond=0)
    if captured.date().isoformat() == "2026-11-19" and time(13, 40) <= minute <= time(15, 30):
        return "채드윅"
    if captured.date().isoformat() == "2026-11-20" and time(10) <= minute <= time(11, 30):
        return "제물포"
    return "이동"


def jpeg_bytes(source: Path) -> bytes:
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
        if "A" in image.getbands() or "transparency" in image.info:
            rgba = image.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, "white")
            rgb.paste(rgba, mask=rgba.getchannel("A"))
        else:
            rgb = image.convert("RGB")
        # 출력에는 위치가 포함될 수 있는 원본 EXIF를 복사하지 않음.
        with BytesIO() as output:
            rgb.save(output, "JPEG", quality=85)
            return output.getvalue()


def write_atomically(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.close()
            temporary_path.replace(target)
        finally:
            temporary_path.unlink(missing_ok=True)


def organize(visit: Path) -> int:
    inbox = visit / "inbox"
    photos = visit / "photos"
    index = photos / "INDEX.md"
    index_text = index.read_text(encoding="utf-8") if index.exists() else INDEX_HEADER
    indexed = {}
    for link, key in SOURCE_ROW.findall(index_text):
        relative = unquote(link)
        if UNKNOWN_FILE.fullmatch(relative) or (
            "/" not in relative and MINUTE_SLOT.fullmatch(relative)
        ):
            indexed[key] = Path(relative)
    number = max(map(int, PHOTO_NUMBER.findall(index_text)), default=0)
    slots = defaultdict(int)
    for path in [*photos.glob("*.jpg"), *indexed.values()]:
        match = MINUTE_SLOT.fullmatch(path.name)
        if match:
            minute, slot = match.groups()
            slots[minute] = max(slots[minute], int(slot or 1))

    sources = sorted(
        path for path in inbox.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ) if inbox.is_dir() else []
    failed = 0
    if any(path.suffix.lower() == ".heic" for path in sources):
        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            print("HEIC 처리에는 pillow-heif 설치가 필요합니다.", file=sys.stderr)
            decodable = [path for path in sources if path.suffix.lower() != ".heic"]
            failed = len(sources) - len(decodable)
            sources = decodable
        else:
            register_heif_opener()

    pending = []
    unknown = []
    for source in sources:
        # inbox는 추가 전용이므로 파일명으로 기존 P번호를 찾을 수 있음.
        key = sha256(source.name.encode("utf-8")).hexdigest()
        existing = indexed.get(key)
        if existing is not None and existing.parent == Path("_시각미상"):
            unknown.append((source, existing))
        if existing is not None and (photos / existing).is_file():
            continue
        try:
            pending.append((capture_time(source), source, key, existing))
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            print(f"{source.name}: {error}", file=sys.stderr)
            failed += 1

    copied = 0
    pending.sort(key=lambda item: (item[0] is None, item[0], item[1].name))
    for captured, source, key, existing in pending:
        try:
            data = jpeg_bytes(source)
            if existing is None:
                number += 1
                label = f"사진{number:02d}"
                if captured is None:
                    relative = Path("_시각미상") / f"{label}.jpg"
                    time_label, location = "미상", "미상"
                else:
                    minute = captured.strftime("%H%M")
                    slots[minute] += 1
                    slot = slots[minute]
                    prefix = minute if slot == 1 else f"{minute}-{slot}"
                    location = location_at(captured)
                    relative = Path(f"{prefix}_{location}_{label}.jpg")
                    time_label = captured.strftime("%Y-%m-%d %H:%M:%S")
                link = quote(relative.as_posix())
                row = (
                    f"| P{number:02d} | [{relative.as_posix()}]({link}) "
                    f"<!-- inbox-key:{key} --> | {time_label} | {location} | | |\n"
                )
                updated_index = index_text.rstrip("\n") + "\n" + row
                # 먼저 번호를 저장해 두어 JPEG 쓰기가 중단돼도 재실행 시 같은 번호로 복원함.
                write_atomically(index, updated_index.encode("utf-8"))
                index_text = updated_index
                if captured is None:
                    unknown.append((source, relative))
            else:
                relative = existing
            write_atomically(photos / relative, data)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            print(f"{source.name}: {error}", file=sys.stderr)
            failed += 1
            continue
        print(f"{source.name} → {relative.as_posix()}")
        copied += 1

    if not index.exists():
        write_atomically(index, index_text.encode("utf-8"))
    print(f"촬영 시각 미상 {len(unknown)}장")
    for source, relative in unknown:
        print(f"- {source.name} → {relative.as_posix()}")
    print(f"저장 {copied}장, 오류 {failed}건 → {index}")
    return int(failed > 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("visit", type=Path, nargs="?", default=DEFAULT_VISIT)
    visit = parser.parse_args().visit.resolve()
    if not visit.is_dir():
        parser.error(f"방문 폴더가 없습니다: {visit}")
    # 같은 방문 폴더를 대상으로 실행할 때 사진 번호를 순차적으로 부여함.
    lock_key = sha256(str(visit).encode("utf-8")).hexdigest()
    lock_path = Path(gettempdir()) / f"organize-photos-{lock_key}.lock"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return organize(visit)


if __name__ == "__main__":
    raise SystemExit(main())
