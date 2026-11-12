
"""SKN36 노인복지 챗봇 LangGraph.

실행 흐름:
Safety → Intent Check → Hybrid Retrieval → Evidence Check → Answer

PostgreSQL 대화 기억과 FastAPI용 ask_welfare() 함수 유지.
"""

from __future__ import annotations

import argparse
import json
import os

from functools import lru_cache
from typing import Any, Callable

from .state import WelfareState

from .safety import (
    safety_node,
    route_after_safety,
    urgent_response_node,
)

from .intent_check import (
    make_intent_node,
    route_after_intent,
    intent_response_node,
)

from .welfare_retrieval import (
    make_retrieval_node,
    mock_retrieve,
)

from .evidence_check import (
    make_evidence_node,
    route_after_evidence,
    insufficient_evidence_node,
)

from .welfare_answer import make_answer_node


def build_graph(
    *,
    mock: bool = False,
    retriever: Callable[..., dict[str, Any]] | None = None,
    llm_call: Callable[[str, str], str] | None = None,
    mode: str = "hybrid",
):
    """Safety, Intent, Retrieval, Evidence, Answer 노드를 연결한다."""

    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError as exc:
        raise RuntimeError(
            "langgraph가 설치되지 않았습니다."
        ) from exc

    # 1. 검색기 준비
    if retriever is None:
        if mock:
            retriever = mock_retrieve
        else:
            from src.retrieval.hybrid_retriever import retrieve_welfare
            retriever = retrieve_welfare

    # 2. 답변 생성 LLM 준비
    if llm_call is None:
        from src.generation.llm import call_llm
        llm_call = call_llm

    # 3. LangGraph 생성
    graph = StateGraph(WelfareState)

    # -----------------------------------
    # 노드 등록
    # -----------------------------------

    graph.add_node(
        "safety",
        safety_node,
    )

    graph.add_node(
        "urgent_response",
        urgent_response_node,
    )

    graph.add_node(
        "intent_check",
        make_intent_node(mock=mock),
    )

    graph.add_node(
        "intent_response",
        intent_response_node,
    )

    graph.add_node(
        "welfare_retrieval",
        make_retrieval_node(
            retriever,
            mode=mode,
        ),
    )

    graph.add_node(
        "evidence_check",
        make_evidence_node(
            mock=mock,
            llm_call=llm_call,
        ),
    )

    graph.add_node(
        "insufficient_evidence",
        insufficient_evidence_node,
    )

    graph.add_node(
        "welfare_answer",
        make_answer_node(
            llm_call,
            mock=mock,
        ),
    )

    # -----------------------------------
    # ① Safety Branch
    # -----------------------------------

    graph.add_edge(
        START,
        "safety",
    )

    graph.add_conditional_edges(
        "safety",
        route_after_safety,
        {
            "urgent": "urgent_response",
            "continue": "intent_check",
        },
    )

    # 위험 질문은 검색 없이 바로 종료
    graph.add_edge(
        "urgent_response",
        END,
    )

    # -----------------------------------
    # ② Intent Check
    # -----------------------------------

    graph.add_conditional_edges(
        "intent_check",
        route_after_intent,
        {
            "search": "welfare_retrieval",
            "respond": "intent_response",
        },
    )

    # 모호한 질문 및 서비스 범위 밖 질문
    graph.add_edge(
        "intent_response",
        END,
    )

    # -----------------------------------
    # ③ Hybrid Retriever
    # -----------------------------------

    graph.add_edge(
        "welfare_retrieval",
        "evidence_check",
    )

    # -----------------------------------
    # ④ Evidence Check
    # -----------------------------------

    graph.add_conditional_edges(
        "evidence_check",
        route_after_evidence,
        {
            "answer": "welfare_answer",
            "fallback": "insufficient_evidence",
        },
    )

    # 근거가 부족한 경우
    graph.add_edge(
        "insufficient_evidence",
        END,
    )

    # -----------------------------------
    # ⑤ Answer
    # -----------------------------------

    graph.add_edge(
        "welfare_answer",
        END,
    )

    return graph.compile()


@lru_cache(maxsize=2)
def _default_graph(mock: bool):
    """일반/Mock LangGraph 객체를 재사용한다."""
    return build_graph(mock=mock)


def ask_welfare(
    question: str,
    session_id: str | None = None,
    *,
    mock: bool = False,
    memory_enabled: bool | None = None,
    region: dict[str, Any] | None = None,
) -> dict:
    """FastAPI에서 호출하는 노인복지 챗봇 함수."""

    # 입력 검증
    if not isinstance(question, str) or not question.strip():
        raise ValueError(
            "question은 비어 있을 수 없습니다."
        )

    question = question.strip()

    if len(question) > 2000:
        raise ValueError(
            "question은 최대 2000자입니다."
        )

    # PostgreSQL 대화 기억 사용 여부
    if memory_enabled is None:
        from dotenv import load_dotenv

        load_dotenv()

        memory_enabled = (
            os.getenv(
                "CHAT_MEMORY_ENABLED",
                "false",
            ).lower() == "true"
        )

    # PostgreSQL 대화 기억 활성화
    if memory_enabled and not mock:
        from src.memory.session_manager import run_chat_session

        return run_chat_session(
            question,
            session_id,
            lambda state: _default_graph(mock).invoke({**state, "region": region}),
        )

    # 일반 실행 및 Mock 실행
    result = _default_graph(mock).invoke(
        {
            "question": question,
            "session_id": session_id,
            "region": region,
        }
    )

    return {
    "answer": result["answer"],
    "sources": result.get("sources", []),
    "safety_status": result.get("safety_status", "normal"),
    "answer_status": result["answer_status"],
    "session_id": session_id,
    "choices": result.get("choices", []),
}


if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "question",
        nargs="?",
        default="기초연금은 어떻게 신청하나요?",
    )

    parser.add_argument(
        "--mock",
        action="store_true",
        help="DB/LLM 없이 흐름 테스트",
    )

    args = parser.parse_args()

    result = ask_welfare(
        args.question,
        mock=args.mock,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
