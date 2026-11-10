"""LangGraph Step 2: Safety → (긴급 응답 | 향후 Retrieval 연결 자리)."""
from __future__ import annotations
from .state import WelfareState
from .safety import safety_node, route_after_safety, urgent_response_node, pending_retrieval_node


def build_graph():
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError as exc:
        raise RuntimeError("langgraph가 설치되지 않았습니다: pip install langgraph") from exc
    graph = StateGraph(WelfareState)
    graph.add_node("safety", safety_node)
    graph.add_node("urgent_response", urgent_response_node)
    graph.add_node("pending_retrieval", pending_retrieval_node)
    graph.add_edge(START, "safety")
    graph.add_conditional_edges(
        "safety", route_after_safety,
        {"urgent": "urgent_response", "continue": "pending_retrieval"},
    )
    graph.add_edge("urgent_response", END)
    graph.add_edge("pending_retrieval", END)
    return graph.compile()


def ask_welfare(question: str, session_id: str | None = None) -> dict:
    """FastAPI에 전달할 잠정 인터페이스. 세션 저장은 아직 구현하지 않음."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 비어 있을 수 없습니다.")
    result = build_graph().invoke({"question": question.strip(), "session_id": session_id})
    return {
        "answer": result["answer"],
        "sources": result.get("sources", []),
        "safety_status": result.get("safety_status", "normal"),
        "answer_status": result["answer_status"],
        "session_id": session_id,
    }


if __name__ == "__main__":
    import json
    for question in ("기초연금 신청 방법", "요즘 너무 외로워요", "죽고 싶어요"):
        print(json.dumps(ask_welfare(question), ensure_ascii=False, indent=2))
