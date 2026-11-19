from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Block:
    text: str
    type: str = "text"  # text | table | heading
    page: int = 0
    section: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class ParsedDoc:
    blocks: list[Block]
    page_count: int = 0
    meta: dict = field(default_factory=dict)


_WS = re.compile(r"[ \t\u3000]+")
_MULTI_NL = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt", ".xlsx", ".xlsm"}


def extension_of(filename: str) -> str:
    return Path(filename).suffix.lower()


def parse_bytes(filename: str, data: bytes) -> ParsedDoc:
    ext = extension_of(filename)
    if ext == ".pdf":
        return _parse_pdf(data)
    if ext == ".docx":
        return _parse_docx(data)
    if ext in {".md", ".markdown"}:
        return _parse_markdown(data)
    if ext in {".txt"}:
        return _parse_text(data)
    if ext in {".xlsx", ".xlsm"}:
        return _parse_xlsx(data)
    raise ValueError(f"不支持的文件类型: {ext or filename}")


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gb18030", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _parse_pdf(data: bytes) -> ParsedDoc:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    blocks: list[Block] = []
    empty_pages: list[int] = []
    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = clean_text(page.extract_text() or "")
        except Exception:  # noqa: BLE001  # pragma: no cover - malformed pdf
            text = ""
        if text:
            blocks.append(Block(text=text, page=idx))
        else:
            empty_pages.append(idx)
    meta: dict = {"pages": len(reader.pages)}
    if empty_pages:
        meta["empty_pages"] = empty_pages[:50]
        meta["warning"] = "部分页面无文本层，可能是扫描件，需要 OCR"
    return ParsedDoc(blocks=blocks, page_count=len(reader.pages), meta=meta)


def _parse_docx(data: bytes) -> ParsedDoc:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    section = ""
    buffer: list[str] = []
    page = 1

    def flush() -> None:
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            blocks.append(Block(text=clean_text(body), page=page, section=section))
        buffer = []

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            text = clean_text(item.text)
            if not text:
                continue
            style = (item.style.name or "").lower() if item.style is not None else ""
            is_heading = style.startswith(("heading", "标题")) or bool(
                re.match(r"^(第[一二三四五六七八九十百]+[章节]|[0-9]+(\.[0-9]+){0,3}\s+\S)", text)
            )
            if is_heading and len(text) <= 80:
                flush()
                section = text
                blocks.append(Block(text=text, type="heading", page=page, section=section))
            else:
                buffer.append(text)
        elif isinstance(item, Table):
            flush()
            rows = []
            for row in item.rows:
                cells = [clean_text(c.text).replace("\n", " ") for c in row.cells]
                rows.append(" | ".join(cells))
            table_text = "\n".join(r for r in rows if r.strip(" |"))
            if table_text:
                blocks.append(
                    Block(text=table_text, type="table", page=page, section=section)
                )
    flush()
    return ParsedDoc(blocks=blocks, page_count=page, meta={"kind": "docx"})


def _parse_markdown(data: bytes) -> ParsedDoc:
    text = clean_text(_decode(data))
    blocks: list[Block] = []
    section = ""
    buffer: list[str] = []
    in_code = False

    def flush() -> None:
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            blocks.append(Block(text=clean_text(body), section=section, page=1))
        buffer = []

    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            buffer.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if heading and not in_code:
            flush()
            section = heading.group(2).strip()
            blocks.append(Block(text=section, type="heading", section=section, page=1))
            continue
        if line.strip().startswith("|") and not in_code:
            buffer.append(line)
            if len(buffer) > 200:
                flush()
            continue
        if not line.strip():
            flush()
        else:
            buffer.append(line)
    flush()
    return ParsedDoc(blocks=blocks, page_count=1, meta={"kind": "markdown"})


def _parse_text(data: bytes) -> ParsedDoc:
    text = clean_text(_decode(data))
    blocks = [Block(text=p.strip(), page=1) for p in text.split("\n\n") if p.strip()]
    if not blocks and text:
        blocks = [Block(text=text, page=1)]
    return ParsedDoc(blocks=blocks, page_count=1, meta={"kind": "text"})


def _parse_xlsx(data: bytes) -> ParsedDoc:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    blocks: list[Block] = []
    for sheet in wb.worksheets:
        rows: list[str] = []
        header = ""
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if v is None else str(v).replace("\n", " ").strip() for v in row]
            if not any(cells):
                continue
            line = " | ".join(cells).strip(" |")
            if not line:
                continue
            if not header:
                header = line
            rows.append(line)
        if rows:
            blocks.append(
                Block(
                    text="\n".join(rows),
                    type="table",
                    section=sheet.title,
                    page=1,
                    meta={"sheet": sheet.title, "rows": len(rows)},
                )
            )
    return ParsedDoc(blocks=blocks, page_count=1, meta={"kind": "xlsx"})