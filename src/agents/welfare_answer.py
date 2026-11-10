"""Answer-generation node with careful source handling and missing-evidence fallback."""
from __future__ import annotations
import json
from typing import Any, Callable
from .state import WelfareState
from src.generation.prompts import SYSTEM_PROMPT


def source_from_doc(doc: dict[str, Any]) -> dict[str, Any] | None:
    md = doc.get("metadata") or {}
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


def make_answer_node(llm_call: Callable[[str, str], str], *, mock: bool = False):
    def node(state: WelfareState) -> WelfareState:
        result = state.get("retrieval_result", {})
        docs = state.get("retrieved_docs", [])
        graph = state.get("graph_results", [])
        is_mock = mock or result.get("verification_level") == "mock_only"
        has_evidence = bool(result.get("has_evidence", bool(docs or graph)))
        # Graph-only rows may lack verified source documents; do not treat them as factual evidence yet.
        if not has_evidence or (not docs and not is_mock):
            return {
                "answer": "확인할 수 있는 복지정책 근거를 찾지 못했습니다. 지역이나 필요한 지원 종류를 조금 더 알려주시겠어요?",
                "answer_status": "no_evidence", "sources": [],
            }
        if is_mock:
            return {
                "answer": "[테스트 응답] 현재는 가상 검색 자료로 LangGraph 흐름을 확인 중입니다. 실제 정책 안내는 DB 연결 및 검증 후 가능합니다.",
                "answer_status": "no_evidence", "sources": [],
            }
        # Limit untrusted evidence size before sending to an LLM.
        pieces = [{"text": str(d.get("text", ""))[:2400], "title": d.get("title"),
                   "parent_id": d.get("parent_id"), "source_url": d.get("source_url")}
                  for d in docs[:5]]
        graph_facts = graph[:5]
        prompt = json.dumps({
            "question": state["question"],
            "recent_history": state.get("history", [])[-4:],
            "documents": pieces,
            "graph_information_unverified_for_eligibility": graph_facts,
            "verification_notes": result.get("warnings", []),
        }, ensure_ascii=False, default=str)
        if state.get("safety_status") == "distress":
            prompt += "\n사용자가 정서적 어려움을 나타냈으므로, 먼저 짧게 공감하고 이용 가능한 지원 정보만 근거와 함께 안내하세요."
        try:
            answer = llm_call(SYSTEM_PROMPT, prompt)
            if not answer or not answer.strip():
                raise ValueError("LLM 빈 응답")
        except Exception as exc:
            # Do not expose API keys or raw provider errors to end users.
            return {"answer": "답변을 생성하는 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.",
                    "answer_status": "error", "sources": [], "generation_error_type": type(exc).__name__}
        sources = [src for d in docs if (src := source_from_doc(d)) is not None]
        return {"answer": answer.strip(), "answer_status": "answered", "sources": sources}
    return node
