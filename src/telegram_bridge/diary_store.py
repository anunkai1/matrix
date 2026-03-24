from __future__ import annotations

import base64
import datetime as dt
import json
import math
import os
import shutil
import ssl
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from PIL import Image


DEFAULT_DIARY_REMOTE_ROOT = "/Diary"
WORD_EMUS_PER_INCH = 914400
WORD_MAX_IMAGE_WIDTH_EMUS = int(6.0 * WORD_EMUS_PER_INCH)


@dataclass
class DiaryPhoto:
    relative_path: str
    caption: str


@dataclass
class DiaryEntry:
    entry_id: str
    created_at: str
    time_label: str
    title: str
    text_blocks: List[str]
    voice_transcripts: List[str]
    notes: List[str]
    photos: List[DiaryPhoto]


def diary_mode_enabled(config) -> bool:
    return bool(getattr(config, "diary_mode_enabled", False))


def diary_timezone(config) -> ZoneInfo:
    name = (getattr(config, "diary_timezone", "") or "Australia/Brisbane").strip()
    return ZoneInfo(name)


def diary_local_root(config) -> Path:
    root = (getattr(config, "diary_local_root", "") or "").strip()
    if root:
        return Path(root)
    state_dir = (getattr(config, "state_dir", "") or "").strip()
    return Path(state_dir) / "diary"


def diary_nextcloud_enabled(config) -> bool:
    return bool(getattr(config, "diary_nextcloud_enabled", False))


def diary_day_slug(day: dt.date) -> str:
    return day.isoformat()


def diary_docx_filename(day: dt.date) -> str:
    return f"{diary_day_slug(day)} - Diary.docx"


def diary_day_json_path(config, day: dt.date) -> Path:
    root = diary_local_root(config)
    return root / "days" / day.strftime("%Y") / day.strftime("%m") / f"{diary_day_slug(day)}.json"


def diary_day_assets_dir(config, day: dt.date) -> Path:
    root = diary_local_root(config)
    return root / "days" / day.strftime("%Y") / day.strftime("%m") / f"{diary_day_slug(day)}-assets"


def diary_day_docx_path(config, day: dt.date) -> Path:
    root = diary_local_root(config)
    return root / "exports" / day.strftime("%Y") / day.strftime("%m") / diary_docx_filename(day)


def diary_day_remote_docx_path(config, day: dt.date) -> Optional[str]:
    remote_root = (getattr(config, "diary_nextcloud_remote_root", "") or "").strip()
    if not remote_root:
        remote_root = DEFAULT_DIARY_REMOTE_ROOT
    if not remote_root.startswith("/"):
        remote_root = f"/{remote_root}"
    remote_root = remote_root.rstrip("/")
    if not remote_root:
        remote_root = DEFAULT_DIARY_REMOTE_ROOT
    return f"{remote_root}/{day.strftime('%Y')}/{day.strftime('%m')}/{diary_docx_filename(day)}"


def sanitize_file_stem(value: str) -> str:
    out = []
    for char in value:
        if char.isalnum() or char in ("-", "_", "."):
            out.append(char)
        else:
            out.append("-")
    cleaned = "".join(out).strip("-._")
    return cleaned or "item"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    os.close(fd)
    try:
        Path(tmp_path).write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def read_day_entries(config, day: dt.date) -> List[DiaryEntry]:
    path = diary_day_json_path(config, day)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return []
    out: List[DiaryEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        photos: List[DiaryPhoto] = []
        for raw_photo in item.get("photos", []):
            if not isinstance(raw_photo, dict):
                continue
            relative_path = str(raw_photo.get("relative_path") or "").strip()
            if not relative_path:
                continue
            photos.append(
                DiaryPhoto(
                    relative_path=relative_path,
                    caption=str(raw_photo.get("caption") or "").strip(),
                )
            )
        out.append(
            DiaryEntry(
                entry_id=str(item.get("entry_id") or "").strip(),
                created_at=str(item.get("created_at") or "").strip(),
                time_label=str(item.get("time_label") or "").strip(),
                title=str(item.get("title") or "").strip(),
                text_blocks=[
                    str(value).strip()
                    for value in item.get("text_blocks", [])
                    if str(value).strip()
                ],
                voice_transcripts=[
                    str(value).strip()
                    for value in item.get("voice_transcripts", [])
                    if str(value).strip()
                ],
                notes=[
                    str(value).strip()
                    for value in item.get("notes", [])
                    if str(value).strip()
                ],
                photos=photos,
            )
        )
    return out


def write_day_entries(config, day: dt.date, entries: Sequence[DiaryEntry]) -> None:
    path = diary_day_json_path(config, day)
    payload = {
        "date": diary_day_slug(day),
        "timezone": str(diary_timezone(config)),
        "entries": [
            {
                "entry_id": entry.entry_id,
                "created_at": entry.created_at,
                "time_label": entry.time_label,
                "title": entry.title,
                "text_blocks": list(entry.text_blocks),
                "voice_transcripts": list(entry.voice_transcripts),
                "notes": list(entry.notes),
                "photos": [
                    {
                        "relative_path": photo.relative_path,
                        "caption": photo.caption,
                    }
                    for photo in entry.photos
                ],
            }
            for entry in entries
        ],
    }
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=True) + "\n")


def copy_photo_to_day_assets(
    config,
    day: dt.date,
    source_path: str,
    entry_id: str,
    index: int,
) -> str:
    source = Path(source_path)
    suffix = source.suffix.lower() or ".jpg"
    asset_dir = diary_day_assets_dir(config, day)
    asset_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{sanitize_file_stem(entry_id)}-{index:02d}{suffix}"
    target = asset_dir / file_name
    shutil.copy2(source, target)
    return str(target.relative_to(diary_local_root(config)))


def append_day_entry(config, day: dt.date, entry: DiaryEntry) -> Path:
    entries = read_day_entries(config, day)
    entries.append(entry)
    write_day_entries(config, day, entries)
    output_path = diary_day_docx_path(config, day)
    render_day_docx(config, day, entries, output_path)
    verify_docx_contains(output_path, [entry.time_label, entry.title or "Diary entry"])
    return output_path


def verify_docx_contains(path: Path, expected_snippets: Sequence[str]) -> None:
    if not path.exists() or path.stat().st_size <= 0:
        raise RuntimeError(f"Diary document was not created correctly: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    for snippet in expected_snippets:
        clean = (snippet or "").strip()
        if clean and clean not in document_xml:
            raise RuntimeError(f"Diary document verification failed for {path}: missing {clean!r}")


def _text_run_xml(text: str, *, bold: bool = False, italic: bool = False) -> str:
    escaped = escape(text)
    rpr = ""
    if bold or italic:
        properties = []
        if bold:
            properties.append("<w:b/>")
        if italic:
            properties.append("<w:i/>")
        rpr = f"<w:rPr>{''.join(properties)}</w:rPr>"
    if not escaped:
        return f"<w:r>{rpr}<w:t></w:t></w:r>"
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escaped}</w:t></w:r>'


def _paragraph_xml(text: str, *, bold: bool = False, italic: bool = False) -> str:
    lines = text.splitlines() or [""]
    runs: List[str] = []
    for index, line in enumerate(lines):
        if index > 0:
            runs.append("<w:r><w:br/></w:r>")
        runs.append(_text_run_xml(line, bold=bold, italic=italic))
    return f"<w:p>{''.join(runs)}</w:p>"


def _image_dimensions_emu(image_path: Path) -> tuple[int, int]:
    with Image.open(image_path) as image:
        width_px, height_px = image.size
    if width_px <= 0 or height_px <= 0:
        return WORD_MAX_IMAGE_WIDTH_EMUS, WORD_MAX_IMAGE_WIDTH_EMUS
    scale = min(1.0, WORD_MAX_IMAGE_WIDTH_EMUS / float(width_px * 9525))
    width_emu = max(1, int(math.floor(width_px * 9525 * scale)))
    height_emu = max(1, int(math.floor(height_px * 9525 * scale)))
    return width_emu, height_emu


def _image_paragraph_xml(rel_id: str, image_name: str, width_emu: int, height_emu: int, doc_pr_id: int) -> str:
    image_name_xml = escape(image_name)
    return (
        "<w:p>"
        "<w:r>"
        "<w:drawing>"
        "<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\">"
        f"<wp:extent cx=\"{width_emu}\" cy=\"{height_emu}\"/>"
        f"<wp:docPr id=\"{doc_pr_id}\" name=\"{image_name_xml}\"/>"
        "<a:graphic xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\">"
        "<a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        "<pic:pic xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        "<pic:nvPicPr>"
        f"<pic:cNvPr id=\"{doc_pr_id}\" name=\"{image_name_xml}\"/>"
        "<pic:cNvPicPr/>"
        "</pic:nvPicPr>"
        "<pic:blipFill>"
        f"<a:blip r:embed=\"{rel_id}\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"/>"
        "<a:stretch><a:fillRect/></a:stretch>"
        "</pic:blipFill>"
        "<pic:spPr>"
        f"<a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"{width_emu}\" cy=\"{height_emu}\"/></a:xfrm>"
        "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom>"
        "</pic:spPr>"
        "</pic:pic>"
        "</a:graphicData>"
        "</a:graphic>"
        "</wp:inline>"
        "</w:drawing>"
        "</w:r>"
        "</w:p>"
    )


def render_day_docx(config, day: dt.date, entries: Sequence[DiaryEntry], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    local_root = diary_local_root(config)
    body_parts: List[str] = []
    image_records: List[tuple[str, Path, str]] = []
    image_counter = 0
    paragraph_id = 1

    body_parts.append(_paragraph_xml(f"Diary entries for {day.isoformat()}", bold=True))
    body_parts.append(_paragraph_xml(""))

    for entry in entries:
        heading = entry.time_label
        if entry.title:
            heading = f"{heading} - {entry.title}"
        body_parts.append(_paragraph_xml(heading, bold=True))
        for block in entry.text_blocks:
            body_parts.append(_paragraph_xml(block))
        if entry.voice_transcripts:
            label = "Voice transcript" if len(entry.voice_transcripts) == 1 else "Voice transcripts"
            body_parts.append(_paragraph_xml(label, italic=True))
            for transcript in entry.voice_transcripts:
                body_parts.append(_paragraph_xml(transcript))
        for note in entry.notes:
            body_parts.append(_paragraph_xml(note, italic=True))
        for photo in entry.photos:
            image_counter += 1
            image_path = local_root / photo.relative_path
            rel_id = f"rId{image_counter}"
            image_name = image_path.name
            image_records.append((rel_id, image_path, image_name))
            width_emu, height_emu = _image_dimensions_emu(image_path)
            body_parts.append(
                _image_paragraph_xml(
                    rel_id=rel_id,
                    image_name=image_name,
                    width_emu=width_emu,
                    height_emu=height_emu,
                    doc_pr_id=paragraph_id,
                )
            )
            paragraph_id += 1
            if photo.caption:
                body_parts.append(_paragraph_xml(photo.caption, italic=True))
        body_parts.append(_paragraph_xml(""))

    body_parts.append(
        "<w:sectPr>"
        "<w:pgSz w:w=\"12240\" w:h=\"15840\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" "
        "w:header=\"708\" w:footer=\"708\" w:gutter=\"0\"/>"
        "</w:sectPr>"
    )

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document "
        "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" "
        "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
        "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
        "xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
        f"<w:body>{''.join(body_parts)}</w:body>"
        "</w:document>"
    )

    rels = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">",
    ]
    for index, (_, image_path, _) in enumerate(image_records, start=1):
        rels.append(
            f"<Relationship Id=\"rId{index}\" "
            "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/image\" "
            f"Target=\"media/{escape(image_path.name)}\"/>"
        )
    rels.append("</Relationships>")
    document_rels_xml = "".join(rels)

    content_types = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>",
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">",
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>",
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>",
        "<Override PartName=\"/word/document.xml\" "
        "ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>",
    ]
    seen_extensions = set()
    for _, image_path, _ in image_records:
        extension = image_path.suffix.lower().lstrip(".")
        if not extension or extension in seen_extensions:
            continue
        seen_extensions.add(extension)
        content_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }.get(extension, "application/octet-stream")
        content_types.append(
            f"<Default Extension=\"{escape(extension)}\" ContentType=\"{content_type}\"/>"
        )
    content_types.append("</Types>")
    content_types_xml = "".join(content_types)

    package_rels_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" "
        "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
        "Target=\"word/document.xml\"/>"
        "</Relationships>"
    )

    fd, tmp_path = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=str(output_path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types_xml)
            archive.writestr("_rels/.rels", package_rels_xml)
            archive.writestr("word/document.xml", document_xml)
            archive.writestr("word/_rels/document.xml.rels", document_rels_xml)
            for _, image_path, image_name in image_records:
                archive.write(image_path, f"word/media/{image_name}")
        os.replace(tmp_path, output_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _nextcloud_auth_header(username: str, app_password: str) -> str:
    token = base64.b64encode(f"{username}:{app_password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _nextcloud_request(
    method: str,
    url: str,
    *,
    username: str,
    app_password: str,
    data: Optional[bytes] = None,
    content_type: Optional[str] = None,
) -> int:
    headers = {
        "Authorization": _nextcloud_auth_header(username, app_password),
    }
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method=method)
    context = ssl._create_unverified_context()
    try:
        with urlopen(request, context=context, timeout=60) as response:
            return int(getattr(response, "status", 200))
    except HTTPError as exc:
        return int(exc.code)


def upload_to_nextcloud(config, local_path: Path, remote_path: str) -> None:
    if not diary_nextcloud_enabled(config):
        return
    base_url = (getattr(config, "diary_nextcloud_base_url", "") or "").strip().rstrip("/")
    username = (getattr(config, "diary_nextcloud_username", "") or "").strip()
    app_password = (getattr(config, "diary_nextcloud_app_password", "") or "").strip()
    if not base_url or not username or not app_password:
        raise RuntimeError("Diary Nextcloud configuration is incomplete")

    encoded_segments = [quote(segment) for segment in remote_path.split("/") if segment]
    if not encoded_segments:
        raise RuntimeError("Diary Nextcloud remote path is empty")
    base_dav = f"{base_url}/remote.php/dav/files/{quote(username)}"

    current_parts: List[str] = []
    for segment in encoded_segments[:-1]:
        current_parts.append(segment)
        dir_url = f"{base_dav}/{'/'.join(current_parts)}"
        status = _nextcloud_request(
            "MKCOL",
            dir_url,
            username=username,
            app_password=app_password,
        )
        if status not in (201, 405):
            raise RuntimeError(f"Diary Nextcloud directory create failed for {remote_path}: HTTP {status}")

    file_url = f"{base_dav}/{'/'.join(encoded_segments)}"
    status = _nextcloud_request(
        "PUT",
        file_url,
        username=username,
        app_password=app_password,
        data=local_path.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    if status not in (201, 204):
        raise RuntimeError(f"Diary Nextcloud upload failed for {remote_path}: HTTP {status}")

    verify_status = _nextcloud_request(
        "HEAD",
        file_url,
        username=username,
        app_password=app_password,
    )
    if verify_status != 200:
        raise RuntimeError(
            f"Diary Nextcloud verification failed for {remote_path}: HTTP {verify_status}"
        )
