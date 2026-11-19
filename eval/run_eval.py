#!/usr/bin/env python
"""P0 evaluation harness: seed the corpus, then measure retrieval + QA quality.

Usage:
    python eval/run_eval.py --seed                 # create KB, upload eval/corpus/*
    python eval/run_eval.py --kb-id <id>           # run the 50-question golden set
    python eval/run_eval.py --kb-id <id> --json eval/report.json

Metrics:
    recall@k        expected evidence keywords appear in the top-k retrieved chunks
    answer_hit      expected keywords appear in the answer (>=50% of them, at least one)
    citation_ok     answer has valid citations (verify.ok) for answerable questions
    refusal_ok      unanswerable questions get an explicit "cannot determine" answer
    latency         wall-clock per question (p50 / p95)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
GOLDEN = ROOT / "golden.jsonl"
TENANT = "default"


def norm(text: str) -> str:
    return "".join((text or "").split()).lower()


async def seed(base: str) -> str:
    async with httpx.AsyncClient(base_url=base, timeout=120) as client:
        headers = {"X-Tenant-Id": TENANT}
        resp = await client.post(
            "/api/kbs",
            json={"name": f"评测知识库-{int(time.time())}", "description": "P0 golden set corpus"},
            headers=headers,
        )
        resp.raise_for_status()
        kb_id = resp.json()["id"]
        print(f"created kb {kb_id}")

        docs = []
        for path in sorted(CORPUS.glob("*.md")):
            with path.open("rb") as fh:
                resp = await client.post(
                    f"/api/kbs/{kb_id}/documents",
                    files={"file": (path.name, fh, "text/markdown")},
                    headers=headers,
                )
            resp.raise_for_status()
            docs.append(resp.json())
            print(f"  uploaded {path.name}")

        deadline = time.time() + 180
        while time.time() < deadline:
            states = []
            for doc in docs:
                r = await client.get(f"/api/documents/{doc['id']}", headers=headers)
                states.append(r.json())
            if all(d["status"] in ("ready", "failed") for d in states):
                break
            await asyncio.sleep(1.5)
        ready = sum(1 for d in states if d["status"] == "ready")
        print(f"ingested {ready}/{len(states)} documents")
        if ready == 0:
            print(json.dumps(states, ensure_ascii=False, indent=2))
            sys.exit(1)
        return kb_id


def load_golden() -> list[dict]:
    items = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
    return items


async def run_one(client, sem, kb_id: str, item: dict, top_k: int) -> dict:
    async with sem:
        headers = {"X-Tenant-Id": TENANT}
        q = item["question"]
        expected = [norm(k) for k in item.get("keywords", [])]
        out = {"id": item["id"], "type": item.get("type", "fact"), "question": q}

        t0 = time.perf_counter()
        try:
            resp = await client.post(
                "/api/chat",
                json={"kb_ids": [kb_id], "question": q, "stream": False},
                headers=headers,
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            out.update(error=str(exc), latency_ms=int((time.perf_counter() - t0) * 1000))
            return out
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)

        answer = body.get("answer", "")
        citations = body.get("citations", [])
        out["answer"] = answer
        out["n_citations"] = len(citations)
        out["verify_ok"] = bool(body.get("verify", {}).get("ok"))
        out["route"] = body.get("route", {})
        out["rounds"] = body.get("rounds")
        out["degraded"] = body.get("degraded", [])

        if item.get("type") == "refusal":
            out["refusal_ok"] = "无法确定" in answer or "资料不足" in answer or "没有" in answer[:20]
            out["passed"] = out["refusal_ok"]
            out["keyword_recall"] = None
            return out

        answer_n = norm(answer)
        matched = [k for k in expected if k in answer_n]
        out["keyword_recall"] = (len(matched) / len(expected)) if expected else 1.0
        need = max(1, (len(expected) + 1) // 2)
        out["answer_hit"] = len(matched) >= need
        out["matched"] = matched
        out["citation_ok"] = out["verify_ok"]
        out["passed"] = out["answer_hit"] and out["citation_ok"]

        try:
            sresp = await client.post(
                "/api/search", json={"kb_ids": [kb_id], "query": q, "top_k": top_k}, headers=headers
            )
            sresp.raise_for_status()
            hits = sresp.json().get("hits", [])
            blob = norm(" ".join(h.get("text", "") for h in hits))
            out["recall_at_k"] = any(k in blob for k in expected) if expected else None
            out["n_hits"] = len(hits)
        except Exception:  # noqa: BLE001
            out["recall_at_k"] = None
        return out


def pct(values, q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * q)))
    return round(ordered[idx], 1)


def summarize(rows: list[dict]) -> dict:
    answerable = [r for r in rows if r["type"] != "refusal" and "error" not in r]
    refusals = [r for r in rows if r["type"] == "refusal" and "error" not in r]
    lat = [r["latency_ms"] for r in rows if "latency_ms" in r]

    def rate(items, key):
        vals = [r.get(key) for r in items if r.get(key) is not None]
        return round(sum(1 for v in vals if v) / len(vals), 4) if vals else None

    return {
        "n_total": len(rows),
        "n_errors": sum(1 for r in rows if "error" in r),
        "n_answerable": len(answerable),
        "n_refusal": len(refusals),
        "answer_hit_rate": rate(answerable, "answer_hit"),
        "citation_ok_rate": rate(answerable, "citation_ok"),
        "recall_at_k": rate(answerable, "recall_at_k"),
        "refusal_ok_rate": rate(refusals, "refusal_ok"),
        "passed_rate": rate(rows, "passed"),
        "keyword_recall_mean": round(
            statistics.mean(r["keyword_recall"] for r in answerable if r.get("keyword_recall") is not None), 4
        )
        if answerable
        else None,
        "latency_p50_ms": pct(lat, 0.5),
        "latency_p95_ms": pct(lat, 0.95),
        "degraded_runs": sum(1 for r in rows if r.get("degraded")),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8101")
    parser.add_argument("--kb-id", default="")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--json", default=str(ROOT / "report.json"))
    args = parser.parse_args()

    kb_id = args.kb_id
    if args.seed:
        kb_id = await seed(args.base_url)
    if not kb_id:
        parser.error("--kb-id is required unless --seed is used")

    items = load_golden()
    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=180) as client:
        rows = await asyncio.gather(*(run_one(client, sem, kb_id, it, args.top_k) for it in items))

    summary = summarize(rows)
    report = {"kb_id": kb_id, "summary": summary, "rows": rows}
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    failures = [r for r in rows if not r.get("passed")]
    if failures:
        print(f"\nnot passed ({len(failures)}):")
        for r in failures[:15]:
            print(f"  {r['id']} [{r['type']}] {r['question']} -> {r.get('answer', r.get('error'))[:80]}")
    print(f"\nreport written to {args.json}")


if __name__ == "__main__":
    asyncio.run(main())