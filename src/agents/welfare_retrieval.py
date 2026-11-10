"""LangGraph retrieval node: explicit mock or actual read-only hybrid retriever."""
from __future__ import annotations
from typing import Any, Callable
from .state import WelfareState

# Synthetic evidence must never appear as a real policy/source citation.
MOCK_EVIDENCE = {
    "question": "",
    "mode": "hybrid",
    "documents": [{
        "id": "mock-uuid-001",
        "chunk_id": "MOCK_CHUNK_001",
        "parent_id": "mock:policy001",
        "record_type": "policy",
        "policy_id": "mock:policy001",
        "text": "[가상 테스트 문서] 지원 여부는 연령, 소득 등 개별 조건에 따라 달라질 수 있으며 공식 확인이 필요합니다.",
        "title": "가상 복지정책 (Mock)",
        "source_url": None,
        "metadata": {"is_mock": True},
    }],
    "graph_results": [],
    "graph_only_results": [],
    "has_evidence": True,
    "verification_level": "mock_only",
    "warnings": ["가상 Mock 자료이며 실제 복지정책 근거가 아닙니다."],
}


def mock_retrieve(question: str, **_: Any) -> dict[str, Any]:
    result = dict(MOCK_EVIDENCE)
    result["question"] = question
    return result



def build_search_question(state: WelfareState) -> str:
    """짧은 후속 질문에 한해 이전 사용자 질문을 검색 맥락으로 사용."""
    question = state["question"].strip()
    history = state.get("history") or []

    followup_words = (
        "그건", "그거", "그 정책", "그 서비스",
        "거기", "그곳", "그럼", "그러면",
        "신청은", "대상은", "조건은",
    )

    is_followup = (
        len(question) <= 80
        and any(word in question for word in followup_words)
    )

    if not is_followup:
        return question

    previous_questions = [
        item.get("content", "").strip()
        for item in history
        if isinstance(item, dict)
        and item.get("role") == "user"
        and isinstance(item.get("content"), str)
        and item.get("content", "").strip()
    ]

    if not previous_questions:
        return question

    previous = previous_questions[-1][:300]
    return f"이전 질문: {previous}\n현재 질문: {question}"


def make_retrieval_node(
    retriever: Callable[..., dict[str, Any]],
    *,
    mode: str = "hybrid",
    k: int = 5,
):
    def node(state: WelfareState) -> WelfareState:
        search_question = build_search_question(state)

        result = retriever(
            search_question,
            mode=mode,
            k=k,
        )

        if not isinstance(result, dict):
            raise TypeError("retriever 반환값은 dict여야 합니다.")

        docs = result.get("documents", [])
        graphs = (
            result.get("graph_results", [])
            or result.get("graph_only_results", [])
        )

        if not isinstance(docs, list) or not isinstance(graphs, list):
            raise TypeError(
                "검색 결과의 documents/graph_results는 list여야 합니다."
            )

        return {
            "retrieved_docs": docs,
            "graph_results": graphs,
            "retrieval_result": result,
        }

    return node

