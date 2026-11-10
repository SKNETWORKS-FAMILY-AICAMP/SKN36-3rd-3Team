
"""Welfare Answer Agent: 검색 근거를 기반으로 LLM 답변 생성."""

from __future__ import annotations

import json
from typing import Any, Callable

from .state import WelfareState
from src.generation.prompts import SYSTEM_PROMPT


def source_from_doc(doc: dict[str, Any]) -> dict[str, Any] | None:
    """검색 문서에서 사용자에게 표시할 출처 정보를 추출한다."""

    md = doc.get("metadata") or {}

    # 테스트용 Mock 문서는 실제 출처로 표시하지 않는다.
    if md.get("is_mock") or str(doc.get("id", "")).startswith("mock-"):
        return None

    kind = doc.get("record_type")

    if kind not in ("policy", "guideline"):
        return None

    return {
        "source_type": kind,
        "title": doc.get("title") or md.get("title") or None,
        "parent_id": doc.get("parent_id"),
        "chunk_id": doc.get("chunk_id"),
        "chunk_uuid": doc.get("id"),
        "document_id": md.get("document_id"),
        "source_url": doc.get("source_url"),
        "page_start": md.get("page_start"),
        "page_end": md.get("page_end"),
        "region_verified": bool(md.get("region_verified", False)),
    }


def make_answer_node(
    llm_call: Callable[[str, str], str],
    *,
    mock: bool = False,
):
    """LangGraph에서 사용할 Welfare Answer 노드를 생성한다."""

    def node(state: WelfareState) -> WelfareState:

        # 1. Retrieval Agent가 반환한 결과 가져오기
        result = state.get("retrieval_result", {})
        docs = state.get("retrieved_docs", [])
        graph = state.get("graph_results", [])

        # 2. Mock 모드인지 확인
        is_mock = (
            mock
            or result.get("verification_level") == "mock_only"
        )

        # 3. 검색 근거 존재 여부 확인
        has_evidence = bool(
            result.get("has_evidence", bool(docs or graph))
        )

        # 근거가 없으면 LLM 답변 생성하지 않음
        if not has_evidence or (not docs and not is_mock):
            return {
                "answer": (
                    "확인할 수 있는 복지정책 근거를 찾지 못했습니다. "
                    "지역이나 필요한 지원 종류를 조금 더 알려주시겠어요?"
                ),
                "answer_status": "no_evidence",
                "sources": [],
            }

        # 4. Mock 모드에서는 실제 정책 답변을 생성하지 않음
        if is_mock:
            return {
                "answer": (
                    "[테스트 응답] 현재는 가상 검색 자료로 "
                    "LangGraph 흐름을 확인 중입니다. "
                    "실제 정책 안내는 DB 연결 및 검증 후 가능합니다."
                ),
                "answer_status": "no_evidence",
                "sources": [],
            }

        # 5. LLM에 전달할 Qdrant 문서 정리
        pieces = [
            {
                "text": str(doc.get("text", ""))[:2400],
                "title": doc.get("title"),
                "parent_id": doc.get("parent_id"),
                "source_url": doc.get("source_url"),
            }
            for doc in docs[:5]
        ]

        # 6. Neo4j 정책 및 PDF 관계 정보
        # 관계 정보는 검색 보조 근거이며 신청 자격의 확정 근거가 아님
        graph_facts = graph[:5]

        guideline_facts = []
        for item in result.get("guideline_results", [])[:5]:
            if not isinstance(item, dict) or not item.get("found"):
                continue

            guideline_facts.append({
                "chunk_id": item.get("chunk_id"),
                "section_id": item.get("section_id"),
                "section": item.get("section"),
                "document": item.get("document"),
            })

        # 7. LLM 프롬프트 생성
        # Qdrant 문서 + Neo4j 정책 관계 + PDF 섹션 정보
        prompt = json.dumps(
            {
                "question": state["question"],
                "recent_history": state.get("history", [])[-4:],

                # Qdrant에서 검색된 정책 및 PDF 본문
                "documents": pieces,

                # Neo4j에서 조회한 정책 관계
                "graph_information_unverified_for_eligibility": graph_facts,

                # Neo4j에서 조회한 PDF 원본/목차 관계
                "guideline_section_information": guideline_facts,

                # 검증 결과 및 주의사항
                "verification_notes": result.get("warnings", []),
            },
            ensure_ascii=False,
            default=str,
        )


        # 정서적 어려움이 감지된 경우
        if state.get("safety_status") == "distress":
            prompt += (
                "\n사용자가 정서적 어려움을 나타냈으므로, "
                "먼저 짧게 공감하고 이용 가능한 지원 정보만 "
                "근거와 함께 안내하세요."
            )

        # 8. LLM 호출
        try:
            answer = llm_call(SYSTEM_PROMPT, prompt)

            if not answer or not answer.strip():
                raise ValueError("LLM 빈 응답")

        except Exception as exc:
            # 내부 API 오류나 API 키를 사용자에게 노출하지 않음
            return {
                "answer": (
                    "답변을 생성하는 중 문제가 발생했습니다. "
                    "잠시 후 다시 시도해 주세요."
                ),
                "answer_status": "error",
                "sources": [],
                "generation_error_type": type(exc).__name__,
            }

        # 9. 사용자에게 보여줄 출처 정리
        sources = [
            source
            for doc in docs
            if (source := source_from_doc(doc)) is not None
        ]

        # 10. 최종 답변 반환
        return {
            "answer": answer.strip(),
            "answer_status": "success",
            "sources": sources,
        }

    return node
