from __future__ import annotations

from typing import Any, Literal, TypedDict

SafetyStatus = Literal["normal", "distress", "urgent"]
AnswerStatus = Literal[
    "success",
    "no_evidence",
    "safety_response",
    "error"
]


class WelfareState(TypedDict, total=False):
    question: str
    session_id: str | None
    history: list[dict[str, str]]
    region: dict[str, Any] | None

    safety_status: SafetyStatus
    safety_reason: str

    retrieved_docs: list[dict[str, Any]]
    graph_results: list[dict[str, Any]]
    retrieval_result: dict[str, Any]

    sources: list[dict[str, Any]]
    answer: str
    answer_status: AnswerStatus
