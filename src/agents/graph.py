
"""SKN36 노인복지 챗봇 LangGraph.

실행 흐름:
Safety → Intent Check → Hybrid Retrieval → Evidence Check → Answer

PostgreSQL 대화 기억과 FastAPI용 ask_welfare() 함수 유지.
"""

from __future__ import annotations

import argparse
import json
import logging
import os

from functools import lru_cache
from typing import Any, Callable

from .state import WelfareState

from .safety import (
    safety_node,
    route_after_safety,
    urgent_response_node,
    safety_note_node,
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

from .welfare_retrieval_v3 import (
    default_region_keys,
    wrap_intent_for_region_answers,
    public_unverified,
    make_grouped_retrieval_node,
    route_after_grouped_retrieval,
    region_clarify_node,
)

logger = logging.getLogger(__name__)


def build_graph(
    *,
    mock: bool = False,
    retriever: Callable[..., dict[str, Any]] | None = None,
    llm_call: Callable[[str, str], str] | None = None,
    mode: str = "hybrid",
    grouped_search: Callable[..., dict[str, Any]] | None = None,
    region_keys: Callable[[], list[str]] | None = None,
):
    """Safety, Intent, Retrieval, Evidence, Answer 노드를 연결한다.

    검색 방식은 그래프를 만들 때 한 번 정한다 (요청 도중에 바뀌지 않는다).
    - 기본(legacy_v1): 3차 하이브리드 검색. 기존 동작 그대로.
    - RAG_RETRIEVAL_MODE=v3: 4차 묶음별 검색. grouped_search 를 직접 주면 그것을 쓴다(테스트용).
    """

    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError as exc:
        raise RuntimeError(
            "langgraph가 설치되지 않았습니다."
        ) from exc

    # 1. 검색기 준비
    use_v3 = grouped_search is not None
    if retriever is None and not use_v3:
        if mock:
            retriever = mock_retrieve
        else:
            from src.retrieval.config import resolve_mode
            retrieval_mode, mode_explicit = resolve_mode()
            if retrieval_mode == "v3":
                use_v3 = True
            else:
                if not mode_explicit:
                    logger.warning("RAG_RETRIEVAL_MODE 가 없어 legacy_v1(3차 검색)으로 동작합니다.")
                from src.retrieval.hybrid_retriever import retrieve_welfare
                retriever = retrieve_welfare

    # 4차: 검색 설정과 지역 이름 목록을 그래프를 만들 때 한 번 정해, 검색 노드와 의도 확인이 같은 것을 쓴다.
    v3_settings, v3_region_keys = None, region_keys
    if use_v3 and grouped_search is None:
        from src.retrieval.config import load_settings
        v3_settings = load_settings()
        v3_region_keys = region_keys or default_region_keys(v3_settings)

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

    # 확인 먼저(distress) 단계에서 상담 전화를 답변 끝에 붙이는 마무리 노드
    graph.add_node(
        "safety_note",
        safety_note_node,
    )

    graph.add_node(
        "intent_check",
        # 4차: 지역을 물은 뒤 사용자가 지역 이름으로 답하면 의도 확인을 건너뛰고 원래 질문으로 검색한다.
        wrap_intent_for_region_answers(make_intent_node(mock=mock), v3_region_keys) if use_v3 else make_intent_node(mock=mock),
    )

    graph.add_node(
        "intent_response",
        intent_response_node,
    )

    if use_v3:
        # 4차: 고른 지역의 정책·전국 자료를 따로 찾는 검색. 지역을 풀 수 없으면 지역 확인으로 끝낸다.
        graph.add_node(
            "welfare_retrieval",
            make_grouped_retrieval_node(grouped_search, settings=v3_settings, region_keys=v3_region_keys),
        )
        graph.add_node(
            "region_clarify",
            region_clarify_node,
        )
    else:
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
        "safety_note",
    )

    # -----------------------------------
    # ③ Hybrid Retriever
    # -----------------------------------

    if use_v3:
        graph.add_conditional_edges(
            "welfare_retrieval",
            route_after_grouped_retrieval,
            {
                "evidence_check": "evidence_check",
                "region_clarify": "region_clarify",
            },
        )
        graph.add_edge(
            "region_clarify",
            "safety_note",
        )
    else:
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
        "safety_note",
    )

    # -----------------------------------
    # ⑤ Answer
    # -----------------------------------

    graph.add_edge(
        "welfare_answer",
        "safety_note",
    )

    # 검색을 거친 모든 경로는 마무리 노드를 지나 끝난다 (긴급 경로는 거치지 않음)
    graph.add_edge(
        "safety_note",
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

        def invoke_with_public_fields(state: dict[str, Any]) -> dict[str, Any]:
            out = _default_graph(mock).invoke({**state, "region": region})
            return {**out, "region_unverified": public_unverified(out)}

        return run_chat_session(
            question,
            session_id,
            invoke_with_public_fields,
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
    "region_unverified": public_unverified(result),
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
