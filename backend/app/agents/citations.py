from __future__ import annotations

import re

_REF = re.compile(r"\[(\d{1,3})\]")


def verify_answer(answer: str, evidence: list[dict]) -> dict:
    refs = {int(m) for m in _REF.findall(answer)}
    n = len(evidence)
    bad_refs = sorted(r for r in refs if r < 1 or r > n)
    citations: list[dict] = []
    for r in sorted(refs):
        if 1 <= r <= n:
            ev = evidence[r - 1]
            citations.append(
                {
                    "index": r,
                    "chunk_id": ev["chunk_id"],
                    "doc_id": ev["doc_id"],
                    "doc_name": ev["doc_name"],
                    "page": ev.get("page", 0),
                    "section": ev.get("section", ""),
                    "snippet": ev["text"][:240],
                    "score": ev.get("score", 0.0),
                    "source": ev.get("source", ""),
                }
            )

    sentences = [s.strip() for s in re.split(r"(?<=[。！？!?；;])", answer) if s.strip()]
    uncited = [
        s for s in sentences
        if not _REF.search(s) and len(s) >= 12 and not s.startswith(("根据现有资料无法确定", "根据知识库资料"))
    ]
    grounded = "无法确定" not in answer and bool(citations)

    issues: list[str] = []
    if bad_refs:
        issues.append("bad_ref:" + ",".join(map(str, bad_refs)))
    if not refs and "无法确定" not in answer:
        issues.append("no_citation")
    if uncited and len(uncited) > max(1, len(sentences) // 3):
        issues.append(f"uncited_sentences:{len(uncited)}")

    return {
        "ok": not issues,
        "issues": issues,
        "grounded": grounded,
        "cited_count": len(citations),
        "sentence_count": len(sentences),
        "citations": citations,
    }


def truncate_evidence(evidence: list[dict], max_chars: int) -> list[dict]:
    out: list[dict] = []
    used = 0
    for ev in evidence:
        cost = len(ev["text"]) + 60
        if out and used + cost > max_chars:
            break
        out.append(ev)
        used += cost
    return out