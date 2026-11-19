from __future__ import annotations

import json

import pytest

POLICY = """星云科技差旅报销制度

第一章 总则
本制度适用于全体正式员工。差旅报销须在费用发生后 30 天内提交。

第二章 差旅标准
一线城市住宿标准为每晚 600 元，二线城市为 450 元。
高铁二等座可全额报销，飞机经济舱需提前 3 天预订。

第三章 审批流程
报销金额 5000 元以下由直属主管审批；超过 20000 元需财务总监李娜复核。
所有报销单必须附带发票扫描件。
"""


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["llm"]["mode"] == "mock"


@pytest.mark.asyncio
async def test_upload_search_and_chat(client):
    kb = (await client.post("/api/kbs", json={"name": "制度库", "description": "测试"})).json()
    kb_id = kb["id"]

    resp = await client.post(
        f"/api/kbs/{kb_id}/documents",
        files={"file": ("policy.txt", POLICY.encode(), "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()

    doc = (await client.get(f"/api/documents/{doc['id']}")).json()
    assert doc["status"] == "ready", doc
    assert doc["chunk_count"] >= 1

    found = await client.post("/api/search", json={"kb_ids": [kb_id], "query": "一线城市住宿标准"})
    assert found.status_code == 200
    hits = found.json()["hits"]
    assert hits and "600" in hits[0]["text"]

    answer = await client.post(
        "/api/chat",
        json={"kb_ids": [kb_id], "question": "一线城市住宿标准是多少？", "stream": False},
    )
    assert answer.status_code == 200, answer.text
    payload = answer.json()
    assert payload["answer"]
    assert payload["citations"], payload
    assert payload["citations"][0]["doc_name"] == "policy"

    conv = (await client.get(f"/api/conversations/{payload['conversation_id']}")).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_chat_stream_events(client):
    kb_id = (await client.post("/api/kbs", json={"name": "kb"})).json()["id"]
    await client.post(
        f"/api/kbs/{kb_id}/documents",
        files={"file": ("policy.txt", POLICY.encode(), "text/plain")},
    )

    events: list[dict] = []
    async with client.stream(
        "POST",
        "/api/chat",
        json={"kb_ids": [kb_id], "question": "审批流程是什么？", "stream": True},
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

    kinds = [e["event"] for e in events]
    assert kinds[0] == "start"
    assert "token" in kinds
    assert kinds[-1] == "done"
    done = events[-1]["data"]
    assert done["answer"]
    assert done["citations"]


@pytest.mark.asyncio
async def test_duplicate_and_bad_type_rejected(client):
    kb_id = (await client.post("/api/kbs", json={"name": "kb"})).json()["id"]
    first = await client.post(
        f"/api/kbs/{kb_id}/documents",
        files={"file": ("a.txt", b"hello policy text", "text/plain")},
    )
    assert first.status_code == 201
    dup = await client.post(
        f"/api/kbs/{kb_id}/documents",
        files={"file": ("b.txt", b"hello policy text", "text/plain")},
    )
    assert dup.status_code == 409
    bad = await client.post(
        f"/api/kbs/{kb_id}/documents",
        files={"file": ("run.exe", b"MZ", "application/octet-stream")},
    )
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_tenant_isolation(client):
    kb_id = (await client.post("/api/kbs", json={"name": "secret"})).json()["id"]
    other = await client.get(f"/api/kbs/{kb_id}", headers={"X-Tenant-Id": "other"})
    assert other.status_code == 404
    mine = await client.get(f"/api/kbs/{kb_id}")
    assert mine.status_code == 200