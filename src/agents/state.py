"""LangGraph 공통 State (2단계: Safety 라우팅).

PostgreSQL 세션 저장 및 RAG 검색은 아직 연결하지 않습니다.
"""
from __future__ import annotations
from typing import Any, Literal, TypedDict

SafetyStatus = Literal["normal", "distress", "urgent"]
AnswerStatus = Literal["success", "no_evidence", "safety_response", "error"]


class WelfareState(TypedDict, total=False):
    question: str
    session_id: str | None
    history: list[dict[str, str]]  # 향후 세션 저장 연결 시에만 사용
    safety_status: SafetyStatus
    safety_reason: str  # UI에 노출하지 않고 디버그/내부 테스트용
    retrieved_docs: list[dict[str, Any]]
    graph_results: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    answer: str
    answer_status: AnswerStatus
