
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
        "title": doc.get("title") or md.get("title"),
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

        # 1. Retrieval Agent 결과 가져오기
        result = state.get("retrieval_result", {})
        docs = state.get("retrieved_docs", [])
        graph = state.get("graph_results", [])

        # 2. Mock 여부 확인
        is_mock = (
            mock
            or result.get("verification_level") == "mock_only"
        )

        # 3. 검색 근거 존재 여부 확인
        has_evidence = bool(
            result.get("has_evidence", bool(docs or graph))
        )

        # 검증된 Qdrant 문서가 없는 경우 답변 생성 방지
        if not has_evidence or (not docs and not is_mock):
            return {
                "answer": (
                    "확인할 수 있는 복지정책 근거를 찾지 못했습니다. "
                    "지역이나 필요한 지원 종류를 조금 더 알려주시겠어요?"
                ),
                "answer_status": "no_evidence",
                "sources": [],
            }

        # 4. Mock 모드에서는 실제 정책 답변 생성 금지
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

        # 5. Qdrant에서 검색한 정책 및 PDF 본문
        pieces = [
            {
                "text": str(doc.get("text", ""))[:2400],
                "title": doc.get("title"),
                "parent_id": doc.get("parent_id"),
                "source_url": doc.get("source_url"),
            }
            for doc in docs[:5]
        ]

        # 6. Neo4j 정책 관계 정보
        # 신청 자격이 검증된 사실로 취급하지 않는다.
        graph_facts = graph[:5]

        # 7. Neo4j PDF 청크 -> 섹션 -> 원본 문서 관계
        guideline_facts = []

        for item in result.get("guideline_results", [])[:5]:

            if not isinstance(item, dict):
                continue

            if not item.get("found"):
                continue

            guideline_facts.append({
                "chunk_id": item.get("chunk_id"),
                "section_id": item.get("section_id"),
                "section": item.get("section"),
                "document": item.get("document"),
            })

        # 8. Neo4j 검수된 관계를 이용한 정책 확장 후보
        # 실제 자격 요건이나 최신성이 검증된 정책 본문이 아님
        expansion_candidates = []

        for item in result.get("graph_expansion_results", [])[:5]:

            if not isinstance(item, dict):
                continue

            policy_id = item.get("parent_id")
            evidence_source = item.get("evidence_source")

            if not policy_id or not evidence_source:
                continue

            expansion_candidates.append({
                "policy_id": str(policy_id),
                "title": str(item.get("title") or "")[:200],
                "evidence_source": str(evidence_source)[:500],
                "review_required": True,
            })

        # 9. LLM 프롬프트 생성
        # 정책 사실은 Qdrant 검색 본문을 근거로 사용한다.
        prompt_data = {
            "question": state["question"],

            # PostgreSQL에서 불러온 최근 대화
            "recent_history": state.get("history", [])[-4:],

            # Qdrant에서 검색된 정책/PDF 본문
            "documents": pieces,

            # Neo4j 정책 관계
            "graph_information_unverified_for_eligibility": graph_facts,

            # Neo4j PDF 섹션 및 원본문서 정보
            "guideline_section_information": guideline_facts,

            # Neo4j 정책 간 관계 확장 결과
            # 추가 검토 후보로만 전달한다.
            "related_policy_candidates_for_review": expansion_candidates,

            # 검증 경고
            "verification_notes": result.get("warnings", []),
        }

        prompt = json.dumps(
            prompt_data,
            ensure_ascii=False,
            default=str,
        )

        # 10. 확장 정책의 잘못된 사용 방지
        if expansion_candidates:
            prompt += (
                "\n주의: related_policy_candidates_for_review는 "
                "검수된 관계를 통해 발견한 관련 정책 후보입니다. "
                "이 정보만으로 정책 혜택, 신청 자격, 지원 금액, "
                "신청 가능 여부를 확정하지 마세요. "
                "정책 사실에 관한 답변은 documents의 "
                "검색 본문에 근거해야 합니다."
            )

        # 11. 정서적 어려움이 감지된 경우
        if state.get("safety_status") == "distress":
            prompt += (
                "\n사용자가 정서적 어려움을 나타냈으므로, "
                "먼저 짧게 공감하고 이용 가능한 지원 정보만 "
                "근거와 함께 안내하세요."
            )

        # 12. LLM 호출
        try:
            answer = llm_call(SYSTEM_PROMPT, prompt)

            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("LLM 빈 응답")

        except Exception as exc:
            # 내부 API 오류 또는 API 키 정보 노출 방지
            return {
                "answer": (
                    "답변을 생성하는 중 문제가 발생했습니다. "
                    "잠시 후 다시 시도해 주세요."
                ),
                "answer_status": "error",
                "sources": [],
                "generation_error_type": type(exc).__name__,
            }

        # 13. 사용자에게 보여줄 출처 목록
        # 실제 Qdrant 검색 문서만 출처로 사용한다.
        sources = [
            source
            for doc in docs
            if (source := source_from_doc(doc)) is not None
        ]

        # 14. 최종 답변 반환
        return {
            "answer": answer.strip(),
            "answer_status": "success",
            "sources": sources,
        }

    return node
