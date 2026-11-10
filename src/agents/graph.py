"""Step 4: LangGraph Safety -> Retrieval -> Answer, optional PostgreSQL chat memory."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Callable

from .state import WelfareState
from .safety import safety_node, route_after_safety, urgent_response_node
from .welfare_retrieval import make_retrieval_node, mock_retrieve
from .welfare_answer import make_answer_node


def build_graph(
    *,
    mock: bool = False,
    retriever: Callable[..., dict[str, Any]] | None = None,
    llm_call: Callable[[str, str], str] | None = None,
    mode: str = "hybrid",
):
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError as exc:
        raise RuntimeError("pip install langgraph를 실행하세요.") from exc
    if retriever is None:
        if mock:
            retriever = mock_retrieve
        else:
            from src.retrieval.hybrid_retriever import retrieve_welfare
            retriever = retrieve_welfare
    if llm_call is None:
        from src.generation.llm import call_llm
        llm_call = call_llm
    graph = StateGraph(WelfareState)
    graph.add_node("safety", safety_node)
    graph.add_node("urgent_response", urgent_response_node)
    graph.add_node("welfare_retrieval", make_retrieval_node(retriever, mode=mode))
    graph.add_node("welfare_answer", make_answer_node(llm_call, mock=mock))
    graph.add_edge(START, "safety")
    graph.add_conditional_edges(
        "safety", route_after_safety,
        {"urgent": "urgent_response", "continue": "welfare_retrieval"},
    )
    graph.add_edge("urgent_response", END)
    graph.add_edge("welfare_retrieval", "welfare_answer")
    graph.add_edge("welfare_answer", END)
    return graph.compile()


@lru_cache(maxsize=2)
def _default_graph(mock: bool):
    return build_graph(mock=mock)


def ask_welfare(
    question: str,
    session_id: str | None = None,
    *,
    mock: bool = False,
    memory_enabled: bool | None = None,
) -> dict:
    """Stable FastAPI contract; memory is opt-in via env/keyword argument.

    CHAT_MEMORY_ENABLED=false (default): no PostgreSQL access.
    CHAT_MEMORY_ENABLED=true: load/save conversation memory, except mock mode.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 비어 있을 수 없습니다.")
    if len(question) > 2000:
        raise ValueError("question은 최대 2000자입니다.")
    if memory_enabled is None:
        from dotenv import load_dotenv
        load_dotenv()
        memory_enabled = os.getenv("CHAT_MEMORY_ENABLED", "false").lower() == "true"
    if memory_enabled and not mock:
        from src.memory.session_manager import run_chat_session
        return run_chat_session(question, session_id, _default_graph(mock).invoke)

    result = _default_graph(mock).invoke({"question": question.strip(), "session_id": session_id})
    return {
        "answer": result["answer"],
        "sources": result.get("sources", []),
        "safety_status": result.get("safety_status", "normal"),
        "answer_status": result["answer_status"],
        "session_id": session_id,
    }


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default="기초연금은 어떻게 신청하나요?")
    parser.add_argument("--mock", action="store_true", help="DB/LLM 없이 임시 테스트")
    args = parser.parse_args()
    print(json.dumps(ask_welfare(args.question, mock=args.mock), ensure_ascii=False, indent=2))
