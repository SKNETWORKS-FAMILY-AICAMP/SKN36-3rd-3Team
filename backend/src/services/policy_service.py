
import os
from functools import lru_cache
from typing import Any

from src.retrieval.hybrid_retriever import retrieve_welfare

from backend.src.schemas.policies import (
    AskRequest,
    AskResult,
    Badge,
    Fallback,
    GuidelineItem,
    PolicyDetail,
    PolicyItem,
    RegionSelection,
    ScopeNotice,
)


def _metadata(doc: dict) -> dict:
    """청크의 최상위 필드와 metadata를 통합한다."""
    payload = doc.get("payload") or {}
    metadata = payload.get("metadata") or {}
    return {
        **payload,
        **metadata,
        **doc,
        **(doc.get("metadata") or {}),
    }


def _field(doc: dict, *names: str) -> Any:
    for name in names:
        value = doc.get(name)
        if value is not None and value != "":
            return value
    return None


def _text(doc: dict) -> str:
    value = _field(
        doc, "text", "content", "page_content",
        "chunk_text", "description"
    )
    return str(value or "")


def _valid_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(
        ("https://", "http://")
    ):
        return value
    return None


def _region_matches(
    doc: dict,
    region: RegionSelection,
) -> bool:
    """명시된 지역 메타데이터로만 필터링한다."""
    scope = str(doc.get("region_scope") or "").lower()

    if scope in ("national", "nationwide", "전국"):
        return True

    sido = str(_field(
        doc, "sido_name", "sidoName", "sido"
    ) or "").strip()

    sigungu = str(_field(
        doc, "sigungu_name", "sigunguName", "sigungu"
    ) or "").strip()

    if region.kind == "nationwide":
        return True

    # 지역 메타데이터가 없으면 지역 정책으로 확정하지 않음
    if not sido or sido != region.sido_name:
        return False

    if region.sigungu_name:
        return sigungu == region.sigungu_name or not sigungu

    return True


def _policy_item(doc: dict) -> PolicyItem | None:
    policy_id = _field(doc, "policy_id", "policyId")
    if not policy_id:
        return None

    return PolicyItem(
        policy_id=str(policy_id),
        title=str(_field(
            doc, "policy_name", "policyName", "title", "name"
        ) or "정책명 확인 필요"),
        sido_name=_field(doc, "sido_name", "sidoName"),
        sigungu_name=_field(doc, "sigungu_name", "sigunguName"),
        snippet=_text(doc)[:240],
        themes=doc.get("themes") or [],
        badges=[Badge(label="검색 결과", tone="info")],
    )


def _guideline_item(doc: dict) -> GuidelineItem | None:
    document_id = _field(doc, "document_id", "documentId")
    if not document_id:
        return None

    start = int(_field(doc, "page_start", "pageStart") or 0)
    end = int(_field(doc, "page_end", "pageEnd") or start)

    return GuidelineItem(
        document_id=str(document_id),
        document_title=str(_field(
            doc, "title", "source", "document_title"
        ) or "안내서"),
        section_title=_field(doc, "section_title", "section"),
        page_start=start,
        page_end=end,
        page_exact=start == end,
        approval="approved",
        snippet=_text(doc)[:240],
        badges=[Badge(label="참고자료", tone="info")],
        source_url=_valid_url(doc.get("source_url")),
    )


def search_policies(request: AskRequest) -> AskResult:
    result = retrieve_welfare(
        question=request.question,
        mode="hybrid",
        k=20,
    )

    items = []
    references = []
    seen_policies = set()
    seen_guidelines = set()

    for raw in result.get("documents", []):
        doc = _metadata(raw)

        if not _region_matches(doc, request.region):
            continue

        record_type = doc.get("record_type")

        if record_type == "policy":
            item = _policy_item(doc)
            if item and item.policy_id not in seen_policies:
                seen_policies.add(item.policy_id)
                items.append(item)

        elif record_type == "guideline":
            item = _guideline_item(doc)
            if item:
                key = (
                    item.document_id,
                    item.page_start,
                    item.page_end,
                )
                if key not in seen_guidelines:
                    seen_guidelines.add(key)
                    references.append(item)

    answer = (
        f"질문과 관련된 복지 정책 {len(items)}건을 찾았습니다."
        if items else
        "조건에 맞는 개별 복지 정책을 확인하지 못했습니다."
    )

    notice = None
    if request.region.kind == "region":
        notice = ScopeNotice(
            reason="preparing_region",
            message=(
                "지역 정보가 확인된 자료만 검색 결과에 포함했습니다. "
                "정확한 신청 자격은 담당 기관에서 확인해 주세요."
            ),
        )

    fallback = None
    if not items:
        fallback = Fallback(
            reason="no_results",
            message=(
                "확인된 정책 결과가 부족합니다. "
                "질문이나 검색 지역을 변경해 보세요."
            ),
        )

    return AskResult(
        question=request.question,
        region=request.region,
        scope_notice=notice,
        answer=answer,
        items=items[:10],
        reference_candidates=references[:10],
        fallback=fallback,
    )


@lru_cache(maxsize=1)
def _qdrant():
    from qdrant_client import QdrantClient

    return QdrantClient(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        api_key=os.getenv("QDRANT_API_KEY") or None,
        timeout=15,
    )


def get_policy_detail(policy_id: str) -> PolicyDetail | None:
    """Qdrant에서 동일 policy_id의 정책 청크를 조회한다."""
    from qdrant_client.models import (
        Filter,
        FieldCondition,
        MatchValue,
    )

    collection = (
        os.getenv("QDRANT_COLLECTION_NAME")
        or os.getenv("QDRANT_COLLECTION")
    )

    if not collection:
        raise RuntimeError(
            "QDRANT_COLLECTION_NAME 환경 변수가 필요합니다."
        )

    condition = MatchValue(value=policy_id)

    points, _ = _qdrant().scroll(
        collection_name=collection,
        scroll_filter=Filter(
            should=[
                FieldCondition(key="policy_id", match=condition),
                FieldCondition(
                    key="metadata.policy_id", match=condition
                ),
            ]
        ),
        limit=100,
        with_payload=True,
        with_vectors=False,
    )

    docs = [
        _metadata(point.payload or {})
        for point in points
    ]

    docs = [
        doc for doc in docs
        if str(_field(doc, "policy_id", "policyId")) == policy_id
        and doc.get("record_type") == "policy"
    ]

    if not docs:
        return None

    doc = docs[0]

    def value(*names: str) -> str | None:
        result = _field(doc, *names)
        return str(result) if result is not None else None

    return PolicyDetail(
        policy_id=policy_id,
        title=value(
            "policy_name", "policyName", "title", "name"
        ) or "정책명 확인 필요",
        summary=value("summary", "description"),
        sido_name=value("sido_name", "sidoName"),
        sigungu_name=value("sigungu_name", "sigunguName"),
        target_text=value("target_text", "targetText"),
        selection_criteria_text=value(
            "selection_criteria_text", "selectionCriteriaText"
        ),
        benefit_text=value("benefit_text", "benefitText"),
        application_text=value(
            "application_text", "applicationText"
        ),
        department=value("department", "agency"),
        source_url=_valid_url(doc.get("source_url")),
        start_date=value("start_date", "startDate"),
        end_date=value("end_date", "endDate"),
        badges=[Badge(label="원본 정보", tone="info")],
    )
