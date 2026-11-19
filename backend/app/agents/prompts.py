from __future__ import annotations

SYSTEM_PROMPT = """你是企业知识库问答助手。请严格依据「参考资料」回答用户问题，并遵守：
1. 只能使用参考资料中的信息，不得编造；资料不足时明确回答“根据现有资料无法确定……”。
2. 每个陈述事实的句子末尾必须标注来源编号，如 [1]、[2][3]；编号必须来自参考资料。
3. 优先直接回答，再给必要的解释；不要复述资料原文的大段内容。
4. 如果资料之间冲突，指出冲突并分别标注来源。
5. 用中文回答，除非用户使用其他语言。"""


def build_answer_messages(question: str, evidence: list[dict], history: list[dict] | None = None) -> list[dict]:
    lines = ["参考资料："]
    for i, ev in enumerate(evidence, start=1):
        head = f"[{i}] 《{ev['doc_name']}》"
        if ev.get("page"):
            head += f" 第{ev['page']}页"
        if ev.get("section"):
            head += f"（{ev['section']}）"
        body = " ".join(ev["text"].split())
        lines.append(f"{head} {body}")
    lines.append("")
    lines.append(f"问题：{question}")
    user = "\n".join(lines)

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-6:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:2000]})
    messages.append({"role": "user", "content": user})
    return messages


def build_router_messages(question: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "判断问题类型，只输出 JSON："
                '{"need_graph": bool, "complexity": "simple|complex", "keywords": [..]}。'
                "涉及实体关系、对比、多跳推理时 need_graph=true。"
            ),
        },
        {"role": "user", "content": question},
    ]