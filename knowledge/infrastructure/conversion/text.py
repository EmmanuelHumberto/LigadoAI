"""Local Markdown/text/DOCX converter."""

from __future__ import annotations

import re
import zipfile
from html import unescape
from pathlib import Path
from xml.etree import ElementTree

from knowledge.domain import ConvertedDocument

_TEXT_EXTENSIONS = {".md", ".txt", ".docx"}
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_WORD_TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
_WORD_PARAGRAPH_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"


class LocalTextDocumentConverter:
    """Convert local text-ish documents into plain text for indexing.

    Some legacy files are real .docx files renamed as .md. Detection is
    content-based, so those files are converted as DOCX instead of being
    decoded as UTF-8 Markdown.
    """

    async def convert(self, source_uri: str) -> ConvertedDocument:
        path = Path(source_uri).expanduser()
        if path.suffix.lower() not in _TEXT_EXTENSIONS:
            raise ValueError(f"unsupported local document extension: {path.suffix}")
        if not path.is_file():
            raise FileNotFoundError(source_uri)

        if _is_docx(path):
            text = _read_docx_text(path)
            content_type = _DOCX_MIME
            detected_type = "docx"
        else:
            text = path.read_text(encoding="utf-8")
            content_type = "text/markdown" if path.suffix.lower() == ".md" else "text/plain"
            detected_type = "text"
        title = _title_from_text(text) or path.stem
        return ConvertedDocument(
            source_uri=str(path),
            text=text,
            content_type=content_type,
            title=title,
            metadata={
                "source_name": path.name,
                "detected_type": detected_type,
            },
        )


def _title_from_text(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
        if stripped:
            return stripped[:80]
    return None


def _is_docx(path: Path) -> bool:
    if path.suffix.lower() == ".docx":
        return True
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"PK\x03\x04" and zipfile.is_zipfile(path)
    except OSError:
        return False


def _read_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("DOCX missing word/document.xml") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid DOCX/ZIP document") from exc

    root = ElementTree.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(_WORD_PARAGRAPH_TAG):
        parts = [
            node.text
            for node in paragraph.iter(_WORD_TEXT_TAG)
            if node.text is not None
        ]
        text = _normalize_docx_text("".join(parts))
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise ValueError("DOCX did not contain extractable text")
    return "\n\n".join(paragraphs)


def _normalize_docx_text(text: str) -> str:
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()
