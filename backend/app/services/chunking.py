from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.services.parsing import Block


@dataclass
class ChunkDraft:
    seq: int
    text: str
    type: str = "text"
    page: int = 0
    section: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def chunk_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.section.encode("utf-8", "ignore"))
        h.update(b"\x00")
        h.update(self.text.encode("utf-8", "ignore"))
        return h.hexdigest()


def _hard_split(text: str, size: int, overlap: int) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    pieces: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind("。"), window.rfind("；"), window.rfind("！"))
            if cut > int(size * 0.55):
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return pieces


def _split_table(text: str, section: str, max_chars: int) -> list[str]:
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []
    header = lines[0] if "|" in lines[0] else ""
    body = lines[1:] if header else lines
    if sum(len(x) + 1 for x in lines) <= max_chars:
        return ["\n".join(lines)]
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for ln in body:
        if size + len(ln) > max_chars and buf:
            out.append("\n".join(([header] if header else []) + buf))
            buf, size = [], 0
        buf.append(ln)
        size += len(ln) + 1
    if buf:
        out.append("\n".join(([header] if header else []) + buf))
    return out


def chunk_blocks(
    blocks: list[Block],
    *,
    chunk_size: int = 600,
    overlap: int = 80,
) -> list[ChunkDraft]:
    """Structure-aware chunking: keeps headings/tables intact, never splits a table row."""
    drafts: list[ChunkDraft] = []
    size = max(120, chunk_size)
    overlap = max(0, min(overlap, size // 2))
    section = ""
    buffer: list[str] = []
    buf_page = 0

    def emit(text: str, *, type_: str = "text", page: int = 0, section_: str = "") -> None:
        body = text.strip()
        if not body:
            return
        drafts.append(
            ChunkDraft(
                seq=len(drafts),
                text=body,
                type=type_,
                page=page,
                section=section_,
            )
        )

    def flush() -> None:
        nonlocal buffer, buf_page
        body = "\n".join(buffer).strip()
        if body:
            for piece in _hard_split(body, size, overlap):
                emit(piece, page=buf_page, section_=section)
        buffer = []
        buf_page = 0

    for block in blocks:
        if block.type == "heading":
            flush()
            section = block.text.strip()
            continue
        if block.type == "table":
            flush()
            for piece in _split_table(block.text, section, max_chars=size * 3):
                emit(piece, type_="table", page=block.page, section_=block.section or section)
            continue

        # text block: split into paragraphs, then pack
        paragraphs = [p.strip() for p in re.split(r"\n{1,}", block.text) if p.strip()]
        for para in paragraphs:
            if len(para) > size:
                flush()
                for piece in _hard_split(para, size, overlap):
                    emit(piece, page=block.page, section_=block.section or section)
                continue
            current = len("\n".join(buffer))
            if buffer and current + len(para) + 1 > size:
                flush()
            if not buffer:
                buf_page = block.page
            buffer.append(para)
    flush()
    return drafts