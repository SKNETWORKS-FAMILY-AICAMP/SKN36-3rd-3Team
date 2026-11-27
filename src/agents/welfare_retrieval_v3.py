"""4차(v3) 검색 노드: 묶음별 검색을 채팅 흐름에 연결한다 (B3).

RAG_RETRIEVAL_MODE=v3 일 때만 그래프에 들어간다. 3차(legacy_v1)·mock 경로는 welfare_retrieval.py 를 그대로 쓴다.

3차와 다른 점
- 화면에서 고른 지역을 검색 전에 Qdrant 필터로 쓴다 (3차는 검색 뒤에 걸렀다).
- 답변 근거(documents)는 지역 정책 + 전국 자료다. 전국을 직접 골랐을 때는 전국 자료 + 지역별 참고 후보다.
- 적용 지역이 확정되지 않은 자료(unverified)는 근거에 넣지 않고, LLM 에도 넘기지 않는다. 화면·API 용 별도 목록으로만 둔다.
- Neo4j 는 같은 데이터 버전을 적재하기 전이라 쓰지 않는다 (벡터 검색만).
- 3차의 식사 질문 전용 재검색(fallback_search_query)은 넣지 않았다. 먼저 측정한 뒤 필요하면 추가한다.
"""
from __future__ import annotations

from typing import Any, Callable

from .state import WelfareState
from .welfare_retrieval import build_search_question

V3_RESULT_MODE = "v3_grouped"   # retrieval_result["mode"]. 근거 검사·답변 단계가 이 값으로 같은 요청의 방식을 안다.

REGION_CLARIFY_ANSWERS = {
    "ambiguous": (
        "말씀하신 지역이 광주광역시인지 경기도 광주시인지 알 수 없어요. "
        "지역을 다시 골라 주시겠어요?"
    ),
    "unknown": (
        "고르신 지역은 지금 가진 자료에서 찾을 수 없어요. "
        "시·도와 시·군·구를 다시 골라 주시겠어요?"
    ),
    "invalid": "지역 선택을 확인하지 못했어요. 시·도와 시·군·구를 다시 골라 주시겠어요?",
}


def is_v3_result(result: dict[str, Any] | None) -> bool:
    return isinstance(result, dict) and result.get("mode") == V3_RESULT_MODE


def make_grouped_retrieval_node(
    search: Callable[..., dict[str, Any]] | None = None,
    *,
    settings: Any = None,
    local_k: int = 5,
    national_k: int = 3,
    unverified_k: int = 3,
):
    """묶음별 검색 노드를 만든다. search 를 주지 않으면 실제 search_grouped 를 쓴다.

    실제 검색을 쓸 때는 노드를 만드는 시점의 설정(컬렉션·데이터 버전·서버)을 그대로 붙잡아 둔다.
    그래프를 만든 뒤 환경 변수가 바뀌어도 같은 그래프가 다른 컬렉션을 검색하지 않게 하기 위해서다.
    """
    if search is None and settings is None:
        from src.retrieval.config import load_settings
        settings = load_settings()

    def node(state: WelfareState) -> WelfareState:
        from src.retrieval import region_rules as R

        try:
            selection = R.selection_from_request(state.get("region"))
        except R.RegionError as exc:
            # 지역 이름을 풀 수 없으면 추측해서 검색하지 않는다. 지역 확인 분기로 보낸다.
            kind = ("ambiguous" if isinstance(exc, R.AmbiguousRegionError)
                    else "unknown" if isinstance(exc, R.UnknownRegionError) else "invalid")
            result = _empty_result(state["question"])
            result["region_error"] = {"kind": kind, "message": str(exc)}
            return {"retrieved_docs": [], "graph_results": [], "retrieval_result": result}

        search_question = state.get("search_query") or build_search_question(state)
        if search is None:
            from src.retrieval import grouped_search
            out = grouped_search.search_grouped(search_question, selection, settings=settings,
                                                local_k=local_k, national_k=national_k, unverified_k=unverified_k)
        else:
            out = search(search_question, selection, local_k=local_k, national_k=national_k, unverified_k=unverified_k)

        # 답변 근거: 지역 정책 먼저, 그다음 전국 자료. 전국을 직접 골랐으면 지역 정책 대신 지역별 참고 후보.
        docs = list(out["local"]) + list(out["national"]) + list(out["reference"])
        result = _empty_result(search_question)
        result.update({
            "documents": docs,
            "has_evidence": bool(docs),
            "selection": {"kind": selection.kind, "sido": selection.sido, "sigungu": selection.sigungu},
            # 근거가 아닌 별도 목록. LLM 프롬프트에 넣지 않는다.
            "unverified_candidates": list(out["unverified"]),
            "grouped_info": out["info"],
            "diagnostics": {"returned": dict(out["info"].get("returned") or {}), "dropped": dict(out["info"].get("dropped") or {}),
                            "short": list(out["info"].get("short") or [])},
        })
        return {"retrieved_docs": docs, "graph_results": [], "retrieval_result": result}

    return node


def _empty_result(question: str) -> dict[str, Any]:
    return {
        "question": question, "mode": V3_RESULT_MODE, "documents": [], "graph_results": [], "graph_only_results": [],
        "guideline_results": [], "graph_expansion_results": [], "unverified_candidates": [], "has_evidence": False,
        "verification_level": "vector_only_v3",
        "warnings": ["정책 관계 정보(Neo4j)는 같은 데이터 버전 적재 전이라 사용하지 않았습니다."],
    }


def route_after_grouped_retrieval(state: WelfareState) -> str:
    result = state.get("retrieval_result") or {}
    return "region_clarify" if result.get("region_error") else "evidence_check"


def region_clarify_node(state: WelfareState) -> WelfareState:
    """지역을 풀 수 없을 때: 검색하지 않고 지역을 다시 고르게 한다."""
    error = (state.get("retrieval_result") or {}).get("region_error") or {}
    answer = REGION_CLARIFY_ANSWERS.get(error.get("kind"), REGION_CLARIFY_ANSWERS["invalid"])
    return {"answer": answer, "answer_status": "no_evidence", "sources": []}


# ───────────── 정책별 관련성 판정 (근거 검사 단계에서 쓴다) ─────────────

RELEVANCE_RULES = """

[추가 규칙: 문서별 관련성]
- documents 의 각 문서에는 번호(no)와 묶음(evidence_group)이 있습니다.
  local 은 사용자가 고른 지역의 정책, national 은 전국 공통 자료, reference 는 다른 지역일 수 있는 지역 정책입니다.
- 질문에 답하는 데 실제로 쓸 수 있는 문서의 번호만 relevant 에 넣으세요. 주제가 다른 문서는 넣지 마세요.
- 같은 지역의 정책이라는 이유만으로 관련 있다고 보지 마세요 (예: 식사 지원 질문에 난임 의료비 정책은 관련 없음).
- 주제가 맞는 정책은 사용자의 신청 자격이 불명확하더라도 relevant 에 넣으세요. 자격 확정과 관련성은 다릅니다.
- region_status 가 candidate 인 지역 정책은 적용 지역이 후보로 분류된 자료입니다. relevant 에 넣는 것은 주제가 맞다는 뜻일 뿐,
  그 지역에 적용된다고 확정하거나 사용자가 받을 수 있다고 판단한 것이 아닙니다.
- verdict 가 sufficient 또는 partial 이면 relevant 는 비어 있으면 안 됩니다.
  verdict 가 insufficient 또는 uncertain 이면 relevant 는 빈 목록이어야 합니다.

반드시 아래 JSON 객체만 반환하세요.

{
  "verdict": "sufficient 또는 partial 또는 insufficient 또는 uncertain",
  "reason": "판단 이유를 짧게",
  "relevant": [관련 있는 문서의 no 를 정수로]
}
"""


def numbered_evidence(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """근거 검사 LLM 에 보낼 문서 목록. 번호·묶음·지역을 붙인다."""
    return [
        {
            "no": i,
            "evidence_group": doc.get("evidence_group"),
            "region": doc.get("region_keys") or [],
            "region_status": (doc.get("metadata") or {}).get("scope_status"),
            "title": doc.get("title"),
            "text": str(doc.get("text") or "")[:1800],
            "record_type": doc.get("record_type"),
            "parent_id": doc.get("parent_id"),
        }
        for i, doc in enumerate(docs, 1)
    ]


def parse_relevance(parsed: dict[str, Any], count: int) -> tuple[str, str, list[int]]:
    """LLM 판정을 검사한다. 모순이 있으면 ValueError (판정 실패로 처리된다)."""
    verdict = parsed.get("verdict")
    if verdict not in ("sufficient", "partial", "insufficient", "uncertain"):
        raise ValueError("잘못된 검증 결과")
    relevant = parsed.get("relevant")
    if not isinstance(relevant, list) or any(isinstance(n, bool) or not isinstance(n, int) for n in relevant):
        raise ValueError("relevant 는 정수 목록이어야 함")
    if len(set(relevant)) != len(relevant) or any(not 1 <= n <= count for n in relevant):
        raise ValueError("relevant 에 중복이나 범위를 벗어난 번호가 있음")
    if (verdict in ("sufficient", "partial")) != bool(relevant):
        raise ValueError("verdict 와 relevant 가 서로 맞지 않음")
    return verdict, str(parsed.get("reason") or "")[:300], sorted(relevant)


def relevance_uncertain(result: dict[str, Any]) -> dict[str, Any]:
    """LLM 이 판단하기 어렵다고 답했을 때. 근거를 건드리지 않고, '관련 정책 없음'으로 기록하지 않는다."""
    updated = dict(result)
    updated["relevance"] = {"status": "uncertain"}
    return updated


def v3_region_fields(result: dict[str, Any], selected: str | None, instructions: str) -> tuple[str | None, str]:
    """LLM 에 넘길 선택 지역과 지역 지침. 시도까지만 고른 경우를 3차 지침과 충돌하지 않게 바꾼다.

    시스템 프롬프트는 selected_region 이 있으면 지역을 다시 묻지 말라고 한다. 시도까지만 골랐을 때 그대로 두면
    시군구를 물어야 한다는 지침과 부딪친다. 그래서 selected_region 은 비우고, 지역 지침에 시도는 이미 골랐다고 적는다.
    """
    selection = result.get("selection") or {}
    if selection.get("kind") != "sido_only":
        return selected, instructions
    sido = selection.get("sido")
    return None, (
        f"사용자가 화면에서 고른 지역은 '{sido}'이고 시·군·구는 고르지 않았습니다. "
        "시·도는 이미 확인됐으므로 다시 묻지 마세요. 시·군·구는 아직 모르므로 물어볼 수 있습니다. "
        "지역 정책은 시·군·구마다 다르므로, 그 시·도 전체에 적용된다고 말하지 마세요."
    )


def apply_relevance(result: dict[str, Any], docs: list[dict[str, Any]], relevant: list[int]) -> tuple[list[dict], dict]:
    """관련 없다고 판정된 문서를 근거에서 완전히 뺀다. 원래 후보는 진단용으로 남긴다."""
    kept = [docs[n - 1] for n in relevant]
    updated = dict(result)
    updated["documents"] = kept
    updated["has_evidence"] = bool(kept)
    updated["candidates_before_relevance"] = [
        {"chunk_id": d.get("chunk_id"), "evidence_group": d.get("evidence_group"), "kept": (i in relevant)}
        for i, d in enumerate(docs, 1)
    ]
    groups = [d.get("evidence_group") for d in kept]
    updated["relevance"] = {
        "status": "judged",
        "kept": {g: groups.count(g) for g in ("local", "national", "reference")},
        # 정상 판정에서 고른 지역의 관련 정책이 하나도 남지 않았는가 (판정 실패와 구분한다)
        "local_policy_found": "local" in groups,
    }
    return kept, updated


def v3_answer_guidance(result: dict[str, Any]) -> str:
    """답변 생성 프롬프트에 붙일 4차 지침. 문구를 다듬는 일은 B5 에서 한다."""
    selection = result.get("selection") or {}
    relevance = result.get("relevance") or {}
    lines = [
        "\ndocuments 의 evidence_group 은 문서의 종류입니다. local 은 사용자가 고른 지역의 정책, national 은 전국 공통 자료, "
        "reference 는 특정 지역의 정책입니다. 지역 정책과 전국 공통 자료를 구분해서 설명하세요.",
        "region_status 가 candidate 인 지역 정책은 적용 지역이 후보로 분류된 자료입니다. 그 지역에 살면 받을 수 있다고 확정하지 말고, "
        "적용 지역과 자격은 담당 기관에서 확인하도록 안내하세요.",
    ]
    if selection.get("kind") == "sido_only":
        lines.append(
            "사용자는 시·도까지만 골랐습니다. local 문서는 그 시·도 안의 특정 시·군·구 정책이므로 어느 시·군·구 것인지(region) 함께 말하고, "
            "시·도 전체에 적용된다고 말하지 마세요. 고른 시·도는 다시 묻지 말고, 빠진 시·군·구만 물어보세요."
        )
    if selection.get("kind") == "nationwide":
        lines.append(
            "reference 문서는 특정 지역 주민을 위한 정책입니다. 어느 지역 것인지(region) 밝히고, 사용자가 그 지역에 사는지 알 수 없으므로 "
            "받을 수 있다고 말하지 마세요. 사는 지역을 물어보세요."
        )
    if selection.get("kind") == "region" and relevance.get("status") == "judged" and not relevance.get("local_policy_found"):
        lines.append(
            "사용자가 고른 지역에서 이 질문과 관련된 정책은 현재 자료에서 찾지 못했습니다. 이 점을 먼저 알리되, "
            "그 지역에 정책이 없다고 단정하지 마세요. 전국 공통 자료를 안내하고 주민센터에 문의해 보도록 권하세요."
        )
    return "\n".join(lines)


def relevance_failed(result: dict[str, Any]) -> dict[str, Any]:
    """판정 자체가 실패했을 때. '관련 정책 없음'과 구분해 기록한다."""
    updated = dict(result)
    updated["relevance"] = {"status": "failed"}
    return updated
