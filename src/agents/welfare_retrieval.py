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




# Explicit nationwide government guides that may lack region_scope in Qdrant payloads.
# Do NOT treat arbitrary PDFs or ambiguous local policies as nationwide.
_NATIONAL_GUIDE_TITLES = (
    "기초연금 사업안내",
    "노인보건복지사업안내",
    "나에게 힘이 되는 복지서비스",
)


def _is_known_national_guide(doc: dict[str, Any], md: dict[str, Any]) -> bool:
    if doc.get("record_type") != "guideline":
        return False
    # An explicitly local region/scope always overrides the title allowlist.
    scope = str(doc.get("region_scope") or md.get("region_scope") or "").strip().lower()
    if scope and scope not in {"national", "nationwide"}:
        return False
    if any(str(doc.get(k) or md.get(k) or "").strip() for k in ("sido_name", "sigungu_name")):
        return False
    title = str(doc.get("title") or md.get("title") or md.get("source_name") or "")
    return any(name in title.replace(" ", "") for name in (n.replace(" ", "") for n in _NATIONAL_GUIDE_TITLES))


def fallback_search_query(question: str) -> str | None:
    """Return a focused query for meal support even if the person does not say 'difficult'.

    E.g. '밥이나 도시락을 지원받고 싶어요' is a concrete welfare request,
    not a vague statement of hunger. Only query; no policy eligibility claim.
    """
    q = "".join(str(question).split())
    meal = any(x in q for x in ("밥", "식사", "끼니", "반찬", "도시락", "식료품", "급식"))
    need = any(x in q for x in (
        "힘들", "어렵", "못", "부족", "없", "챙기", "준비", "배달",
        "지원", "도움", "받고싶", "필요", "해결", "구해",
    ))
    if meal and need:
        return "노인 식사 지원 도시락 배달 밑반찬 경로식당 무료급식 노인맞춤돌봄서비스 신청 대상"
    return None


def _merge_evidence_results(
    primary: dict[str, Any], secondary: dict[str, Any], *, limit: int,
) -> dict[str, Any]:
    """Merge region-approved retrieval results without creating synthetic evidence.

    `primary` is more targeted, so its documents come first. Keep original
    metadata, graph relationships and IDs; never upgrade verification verdicts.
    """
    merged_docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for doc in list(primary.get("documents") or []) + list(secondary.get("documents") or []):
        if not isinstance(doc, dict):
            continue
        key = str(doc.get("chunk_id") or doc.get("id") or "")
        if not key:
            key = f"{doc.get('record_type')}:{doc.get('parent_id')}:{doc.get('text')}"
        if key in seen:
            continue
        seen.add(key)
        merged_docs.append(doc)
        if len(merged_docs) >= limit:
            break

    policy_ids = {d.get("policy_id") for d in merged_docs if d.get("policy_id")}
    chunk_ids = {d.get("chunk_id") for d in merged_docs if d.get("chunk_id")}
    graph_results = [
        g for g in list(primary.get("graph_results") or []) + list(secondary.get("graph_results") or [])
        if isinstance(g, dict) and g.get("policy_id") in policy_ids
    ]
    guideline_results = [
        g for g in list(primary.get("guideline_results") or []) + list(secondary.get("guideline_results") or [])
        if isinstance(g, dict) and g.get("chunk_id") in chunk_ids
    ]
    return {
        **secondary,
        "documents": merged_docs,
        "graph_results": graph_results,
        "guideline_results": guideline_results,
        "graph_expansion_results": [],
        "has_evidence": bool(merged_docs),
        "warnings": list(dict.fromkeys(
            list(primary.get("warnings") or []) + list(secondary.get("warnings") or [])
        )),
    }


def _region_matches(doc: dict[str, Any], region: dict[str, Any] | None) -> bool:
    """Check scope of retrieved document; no region means legacy unfiltered behavior.

    National guidelines/policies remain available for every region.
    Missing or ambiguous local scope is NOT treated as nationwide.
    """
    if not region or region.get("kind") == "nationwide":
        return True
    if region.get("kind") != "region":
        return False

    md = doc.get("metadata") or {}
    if not isinstance(md, dict):
        md = {}

    def value(key):
        return doc.get(key) if doc.get(key) is not None else md.get(key)

    scope = str(value("region_scope") or "").lower()
    if scope in {"national", "nationwide"}:
        return True
    if _is_known_national_guide(doc, md):
        return True

    wanted_sido = str(region.get("sido_name") or "").strip()
    wanted_sigungu = str(region.get("sigungu_name") or "").strip()
    actual_sido = str(value("sido_name") or "").strip()
    actual_sigungu = str(value("sigungu_name") or "").strip()
    if not wanted_sido or actual_sido != wanted_sido:
        return False

    # If district was selected, keep city/province level policy plus exact district.
    if wanted_sigungu:
        return (scope in {"sido", "province"} and not actual_sigungu) or actual_sigungu == wanted_sigungu
    return True


def filter_retrieval_region(
    result: dict[str, Any], region: dict[str, Any] | None,
) -> dict[str, Any]:
    """Filter candidates AND associated graph evidence together; keep original unmodified."""
    if not region or region.get("kind") == "nationwide":
        return result

    docs = [d for d in result.get("documents", []) if isinstance(d, dict) and _region_matches(d, region)]
    policy_ids = {d.get("policy_id") for d in docs if d.get("policy_id")}
    chunk_ids = {d.get("chunk_id") for d in docs if d.get("chunk_id")}
    return {
        **result,
        "documents": docs,
        "graph_results": [g for g in result.get("graph_results", []) if g.get("policy_id") in policy_ids],
        "guideline_results": [g for g in result.get("guideline_results", []) if g.get("chunk_id") in chunk_ids],
        "graph_expansion_results": [],  # expansion has not been independently region-validated
        "has_evidence": bool(docs),
        "region_filter": {"kind": "region", "sido_name": region.get("sido_name"), "sigungu_name": region.get("sigungu_name"), "stage": "post_retrieval"},
    }


def make_retrieval_node(
    retriever: Callable[..., dict[str, Any]],
    *,
    mode: str = "hybrid",
    k: int = 12,
):
    def node(state: WelfareState) -> WelfareState:
        search_question = (
            state.get("search_query")
            or build_search_question(state)
        )

        result = retriever(
            search_question,
            mode=mode,
            k=k,
        )

        if not isinstance(result, dict):
            raise TypeError("retriever 반환값은 dict여야 합니다.")

        raw_count = len(result.get("documents") or [])
        result = filter_retrieval_region(result, state.get("region"))
        docs = result.get("documents", [])

        # Concrete requests for meal/food support benefit from a separate,
        # policy-oriented search even when the first search returned unrelated
        # documents. The previous `if not docs` condition skipped this case.
        retry_query = fallback_search_query(state["question"])
        retry_used = False
        retry_count = 0
        if retry_query and retry_query != search_question:
            retry_result = retriever(retry_query, mode=mode, k=k)
            if not isinstance(retry_result, dict):
                raise TypeError("retriever 재검색 반환값은 dict여야 합니다.")
            retry_result = filter_retrieval_region(retry_result, state.get("region"))
            retry_count = len(retry_result.get("documents") or [])
            retry_used = True
            if retry_count:
                # Prefer matching meal-policy evidence, but retain other
                # region-approved candidates and their traceable citations.
                result = _merge_evidence_results(retry_result, result, limit=k)
                docs = result["documents"]
                result["retry_query_used"] = retry_query

        result["diagnostics"] = {
            "initial_qdrant_hits": raw_count,
            "region_accepted_hits": len(docs),
            "retry_used": retry_used,
            "retry_accepted_hits": retry_count,
        }
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



def select_context_docs(documents: list[dict[str, Any]], limit: int = 8, max_per_section: int = 2) -> list[dict[str, Any]]:
    """Keep Qdrant rank, avoid filling the LLM context with copies of one PDF section."""
    chosen: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    seen: set[str] = set()
    for doc in documents:
        if not isinstance(doc, dict) or not str(doc.get("text") or "").strip():
            continue
        chunk_id = str(doc.get("chunk_id") or doc.get("id") or "")
        if chunk_id and chunk_id in seen:
            continue
        meta = doc.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        if doc.get("record_type") == "guideline":
            section_id = str(doc.get("section_id") or meta.get("section_id") or "")
            if section_id and counts.get(section_id, 0) >= max_per_section:
                continue
            if section_id:
                counts[section_id] = counts.get(section_id, 0) + 1
        if chunk_id:
            seen.add(chunk_id)
        chosen.append(doc)
        if len(chosen) >= limit:
            break
    return chosen
