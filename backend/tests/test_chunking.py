from __future__ import annotations

from app.services.chunking import chunk_blocks
from app.services.parsing import Block


def _text_blocks(text: str, page: int = 1) -> list[Block]:
    return [Block(text=text, type="text", page=page)]


def test_short_block_is_single_chunk():
    drafts = chunk_blocks(_text_blocks("这是一段很短的文字。"), chunk_size=600, overlap=80)
    assert len(drafts) == 1
    assert drafts[0].text == "这是一段很短的文字。"
    assert drafts[0].seq == 0


def test_heading_starts_new_chunk():
    blocks = [
        Block(text="第一章 总则", type="heading", page=1),
        Block(text="本制度适用于全体员工。" * 5, type="text", page=1),
        Block(text="第二章 报销", type="heading", page=1),
        Block(text="差旅报销须在 30 天内提交。" * 5, type="text", page=1),
    ]
    drafts = chunk_blocks(blocks, chunk_size=80, overlap=10)
    sections = {d.section for d in drafts}
    assert "第一章 总则" in sections
    assert "第二章 报销" in sections
    assert all(d.text for d in drafts)


def test_table_rows_repeat_header():
    rows = ["| 城市 | 标准 |"] + [f"| 城市{i} | {400 + i} |" for i in range(40)]
    block = Block(text="\n".join(rows), type="table", page=2)
    drafts = chunk_blocks([block], chunk_size=120, overlap=0)
    assert len(drafts) >= 2
    assert all(d.text.startswith("| 城市 | 标准 |") for d in drafts)


def test_long_text_splits_with_overlap():
    text = "".join(f"第{i}句说明了一些事情。" for i in range(1, 60))
    drafts = chunk_blocks(_text_blocks(text), chunk_size=120, overlap=20)
    assert len(drafts) > 1
    assert all(len(d.text) <= 200 for d in drafts)
    joined = "".join(d.text for d in drafts)
    assert "第1句" in joined and "第59句" in joined
    assert drafts[0].chunk_hash and drafts[0].chunk_hash == drafts[0].chunk_hash