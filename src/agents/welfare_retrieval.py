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


def make_retrieval_node(retriever: Callable[..., dict[str, Any]], *, mode: str = "hybrid", k: int = 5):
    def node(state: WelfareState) -> WelfareState:
        result = retriever(state["question"], mode=mode, k=k)
        if not isinstance(result, dict):
            raise TypeError("retriever 반환값은 dict여야 합니다.")
        docs = result.get("documents", [])
        graphs = result.get("graph_results", []) or result.get("graph_only_results", [])
        if not isinstance(docs, list) or not isinstance(graphs, list):
            raise TypeError("검색 결과의 documents/graph_results는 list여야 합니다.")
        return {
            "retrieved_docs": docs,
            "graph_results": graphs,
            "retrieval_result": result,
        }
    return node
