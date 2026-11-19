from __future__ import annotations

from app.agents.citations import truncate_evidence, verify_answer


def _ev(i: int, text: str = "证据文本") -> dict:
    return {
        "chunk_id": f"c{i}",
        "doc_id": f"d{i}",
        "doc_name": f"文档{i}.pdf",
        "text": text,
        "page": i,
        "section": f"第{i}章",
        "score": 0.5,
        "source": "vector",
    }


def test_verify_ok_with_valid_citations():
    report = verify_answer("一线城市住宿标准是每晚 600 元。[1] 二线城市为 450 元。[2]", [_ev(1), _ev(2)])
    assert report["ok"] is True
    assert report["grounded"] is True
    assert [c["index"] for c in report["citations"]] == [1, 2]
    assert report["citations"][0]["doc_name"] == "文档1.pdf"


def test_verify_flags_out_of_range_refs():
    report = verify_answer("这可能是对的。[9]", [_ev(1)])
    assert report["ok"] is False
    assert any(i.startswith("bad_ref") for i in report["issues"])
    assert report["citations"] == []


def test_verify_flags_missing_citation_when_claims_made():
    report = verify_answer("一线城市住宿标准是每晚 600 元，二线城市为 450 元。", [_ev(1)])
    assert report["ok"] is False
    assert "no_citation" in report["issues"]


def test_verify_allows_refusal_without_citation():
    report = verify_answer("根据现有资料无法确定该问题的答案。", [_ev(1)])
    assert "no_citation" not in report["issues"]
    assert report["grounded"] is False


def test_truncate_evidence_respects_budget():
    items = [_ev(i, "x" * 500) for i in range(1, 6)]
    kept = truncate_evidence(items, max_chars=1200)
    assert 0 < len(kept) < 5
    assert kept[0]["chunk_id"] == "c1"