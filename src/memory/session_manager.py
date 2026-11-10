"""Orchestrate conversational context around a LangGraph invoke call.

The actual LangGraph contains Safety -> Retrieval -> Answer nodes.
This wrapper performs: history read -> LangGraph invoke -> conditional save.
"""
from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

from .conversation_store import load_history, save_exchange, validate_session_id

# Avoid persisting high-risk or emotionally sensitive chat by default.
_SAVE_STATUSES = {"normal"}
_SAVE_ANSWERS = {"success", "no_evidence"}


def run_chat_session(
    question: str,
    session_id: str | None,
    invoke_graph: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    max_history_messages: int = 8,
) -> dict[str, Any]:
    """Create/resume a conversation; return existing FastAPI response contract.

    A UUID alone is not authentication. API must authorize the session owner.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 비어 있을 수 없습니다.")
    question = question.strip()
    if len(question) > 2000:
        raise ValueError("question은 2000자 이하여야 합니다.")
    sid = validate_session_id(session_id) if session_id else str(uuid4())
    history = load_history(sid, max_messages=max_history_messages)
    result = invoke_graph({"question": question, "session_id": sid, "history": history})
    status = result.get("safety_status", "normal")
    answer_status = result.get("answer_status", "error")
    answer = str(result.get("answer") or "")
    if status in _SAVE_STATUSES and answer_status in _SAVE_ANSWERS and answer:
        save_exchange(sid, question, answer)
    return {
        "answer": answer,
        "sources": result.get("sources", []),
        "safety_status": status,
        "answer_status": answer_status,
        "session_id": sid,
    }
