"""정책 목록·상세의 4차(v3) 경로 (B4). RAG_RETRIEVAL_MODE=v3 일 때만 policy_service 가 이쪽을 부른다.

채팅(B3)과 같은 지역 규칙(src/retrieval/region_rules)과 같은 묶음별 검색(src/retrieval/grouped_search)을 쓴다.

- 목록(search_policies_v3): LLM 을 부르지 않는다. 그래서 결과는 "관련 정책"이 아니라 질문과 비슷한 순서의 "후보"다.
  지역 정책 후보 / 전국 자료 / 적용 지역 미확인 자료를 따로 돌려준다.
- 상세(get_policy_detail_v3): 승인된 4차 데이터에서만 찾는다. 여러 청크로 나뉜 본문은 겹치는 부분을 맞춰 이어 붙인다.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from backend.src.schemas.policies import (
    AskRequest, AskResult, Badge, Contact, Fallback, GuidelineItem, PolicyDetail, PolicyItem, ScopeNotice,
)
from src.retrieval import region_rules as R
from src.retrieval.config import RetrievalConfigError, RetrievalSettings, V3_RELEASE_STATUS, load_settings

LIST_K = {"local_k": 10, "national_k": 5, "unverified_k": 5}
# 정책 본문에 나오는 정해진 라벨. 이 목록에 있는 것만 줄 처음에서 라벨로 본다.
SECTION_LABELS = ("사업명", "지역", "사업 개요", "지원 대상", "선정 기준", "지원 내용", "신청 방법", "신청 방식", "담당 부서", "문의처")
_SECTION_RE = re.compile(r"(?m)^(" + "|".join(re.escape(x) for x in SECTION_LABELS) + r"): ?")
MIN_OVERLAP = 20
OPEN_END_DATE = "9999-12-31"   # 원본의 "끝 날짜 없음" 표시. 사용자에게 그대로 보여 주지 않는다.
CONFIRMED_CONTACT = "source_group_confirmed"
# 전화를 걸 수 있는 번호의 꼴: 지역번호-국번-번호 / 국번-번호(1588-0000 등) / 짧은 번호(129 등)
_PHONE_RE = re.compile(r"\d{2,4}-\d{3,4}-\d{4}|\d{4}-\d{4}|\d{3,4}")
_CHUNK_NO_RE = re.compile(r"::(\d+)$")
# 같은 정책의 청크라면 서로 같아야 하는 칸. 다르면 어느 쪽이 맞는지 알 수 없으므로 고르지 않고 멈춘다.
_SAME_ACROSS_CHUNKS = ("title", "department", "contact", "contact_status", "applies_to_keys", "sido_name",
                       "scope_status", "source_url", "start_date", "end_date")
END_LABEL = "담당 부서"   # 모든 정책 본문의 끝부분에 있는 라벨. 없으면 뒤 조각이 빠진 것으로 본다.


def _valid_url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith(("https://", "http://")) else None


def _region_names(keys: list[str]) -> tuple[str | None, str | None]:
    """지역 키 목록에서 화면에 보여 줄 시도·시군구. 여러 시군구에 걸치면 시군구는 비운다."""
    pairs = [k.split("|", 1) for k in keys if "|" in k]
    if not pairs:
        return None, None
    sidos = {p[0] for p in pairs}
    sido = pairs[0][0] if len(sidos) == 1 else None
    return sido, (pairs[0][1] if len(pairs) == 1 else None)


def _policy_item(doc: dict[str, Any], badge: Badge, *, unverified: bool = False) -> PolicyItem:
    md = doc.get("metadata") or {}
    keys = [] if unverified else list(doc.get("region_keys") or [])
    sido, sigungu = _region_names(keys)
    return PolicyItem(
        policy_id=str(doc.get("policy_id")),
        title=str(doc.get("title") or "정책명 확인 필요"),
        sido_name=sido, sigungu_name=sigungu,
        snippet=str(doc.get("text") or "")[:240],
        themes=list(md.get("themes") or []),
        badges=[badge],
        applies_to=keys,
        scope_status=md.get("scope_status"),
        # 등록 시도는 "그 시도에 등록된 자료"라는 뜻일 뿐, 적용 지역이 아니다. 미확인 자료에만 따로 적는다.
        registered_sido=md.get("sido_name") if unverified else None,
    )


def _guideline_item(doc: dict[str, Any]) -> GuidelineItem | None:
    md = doc.get("metadata") or {}
    if not md.get("document_id"):
        return None
    start = int(md.get("page_start") or 0)
    end = int(md.get("page_end") or start)
    return GuidelineItem(
        document_id=str(md["document_id"]),
        document_title=str(doc.get("title") or "안내서"),
        section_title=md.get("section"),
        page_start=start, page_end=end, page_exact=start == end,
        approval="approved" if md.get("approval_status") == "approved" else "pending",
        snippet=str(doc.get("text") or "")[:240],
        badges=[Badge(label="전국 자료", tone="info")],
        source_url=_valid_url(doc.get("source_url")),
    )


def search_policies_v3(request: AskRequest, *, search: Callable[..., dict[str, Any]] | None = None) -> AskResult:
    region = request.region
    try:
        selection = R.selection_from_request(
            {"kind": region.kind, "sido_name": region.sido_name, "sigungu_name": region.sigungu_name})
    except R.RegionError as exc:
        # 지역 이름을 풀 수 없으면 추측해서 검색하지 않고 다시 고르게 한다 (서버 오류가 아니다).
        ambiguous = isinstance(exc, R.AmbiguousRegionError)
        message = ("고르신 지역이 광주광역시인지 경기도 광주시인지 알 수 없어요. 지역을 다시 골라 주세요." if ambiguous
                   else "고르신 지역을 지금 가진 자료에서 찾을 수 없어요. 시·도와 시·군·구를 다시 골라 주세요.")
        return AskResult(
            question=request.question, region=region, answer=message,
            scope_notice=ScopeNotice(reason="unsupported_region", message=message),
            fallback=Fallback(reason="no_results", message="검색 지역을 다시 선택해 주세요."),
        )

    if search is None:
        from src.retrieval.grouped_search import search_grouped as search
    out = search(request.question, selection, **LIST_K)

    if selection.kind == "nationwide":
        badge = Badge(label="지역별 참고 (사는 지역 확인 필요)", tone="info")
        policies = [_policy_item(d, badge) for d in out["reference"]]
    else:
        badge = Badge(label="적용 지역 후보", tone="info")
        policies = [_policy_item(d, badge) for d in out["local"]]
    seen: set[tuple] = set()
    references = []
    for d in out["national"]:
        item = _guideline_item(d)
        key = (item.document_id, item.page_start, item.page_end) if item else None
        if item and key not in seen:
            seen.add(key)
            references.append(item)
    unverified = [_policy_item(d, Badge(label="적용 지역 확인 필요", tone="warn"), unverified=True) for d in out["unverified"]]

    # 이 경로에는 관련성 판정(LLM)이 없다. "관련 정책을 찾았다"고 하지 않고 후보라고 말한다.
    if policies and selection.kind == "nationwide":
        answer = f"여러 지역의 정책 후보 {len(policies)}건입니다. 질문과 비슷한 순서이며, 사는 지역의 정책인지 확인이 필요해요."
    elif policies:
        answer = f"선택한 지역의 정책 후보 {len(policies)}건입니다. 질문과 비슷한 순서이며, 관련이 낮은 정책이 섞여 있을 수 있어요."
    elif selection.kind == "none":
        answer = "지역을 고르면 그 지역의 정책 후보를 함께 찾아 드려요."
    else:
        answer = "선택한 지역에서는 지금 가진 자료로 정책 후보를 찾지 못했어요."

    notice = None
    if selection.kind in ("region", "sido_only"):
        text = "적용 지역이 후보로 분류된 자료입니다. 정확한 적용 지역과 신청 자격은 담당 기관에서 확인해 주세요."
        if selection.kind == "sido_only":
            text = "시·군·구마다 정책이 달라요. 각 후보가 어느 시·군·구의 것인지 확인해 주세요. " + text
        notice = ScopeNotice(reason="preparing_region", message=text)
    fallback = None if policies else Fallback(
        reason="no_results", message="정책 후보가 부족합니다. 질문이나 검색 지역을 바꿔 보세요.")

    return AskResult(
        question=request.question, region=region, scope_notice=notice, answer=answer,
        items=policies[:10], reference_candidates=references[:10], region_unverified=unverified[:10], fallback=fallback,
    )


# ───────────── 정책 상세 ─────────────

def split_contacts(md: dict[str, Any]) -> tuple[list[Contact], str | None]:
    """확인된 문의처만 번호 하나씩 나눠 돌려준다. 원본은 "번호 / 번호 / …" 꼴로 여러 개가 들어 있을 수 있다.

    번호 꼴이 아닌 조각(잘린 번호 등)은 전화 걸기 대상으로 내보내지 않는다.
    """
    unconfirmed = "문의처는 확인이 필요해요. 담당 부서나 주민센터에 문의해 주세요."
    if not md.get("contact") or md.get("contact_status") != CONFIRMED_CONTACT:
        return [], unconfirmed
    label = str(md.get("department") or "문의처")
    pieces = [p.strip() for p in str(md["contact"]).split("/") if p.strip()]
    numbers = list(dict.fromkeys(p for p in pieces if _PHONE_RE.fullmatch(p)))
    if not numbers:
        return [], unconfirmed
    note = None if len(numbers) == len(dict.fromkeys(pieces)) else "일부 번호는 형식을 확인하지 못해 뺐어요. 담당 부서에 확인해 주세요."
    return [Contact(label=label, tel=n) for n in numbers], note


def merge_chunks(texts: list[str]) -> str | None:
    """번호순 청크를 겹치는 부분에 맞춰 이어 붙인다. 정확히 겹치는 곳을 찾지 못하면 None (추측해서 붙이지 않는다)."""
    if not texts:
        return None
    out = texts[0]
    for nxt in texts[1:]:
        size = next((n for n in range(min(len(out), len(nxt)), MIN_OVERLAP - 1, -1) if out.endswith(nxt[:n])), 0)
        if not size:
            return None
        out += nxt[size:]
    return out


def parse_sections(text: str) -> dict[str, str]:
    """본문에서 정해진 라벨(줄 처음의 "라벨: ")만 찾아 라벨별 내용으로 나눈다."""
    marks = list(_SECTION_RE.finditer(text))
    return {m.group(1): text[m.end():(marks[i + 1].start() if i + 1 < len(marks) else len(text))].strip()
            for i, m in enumerate(marks)}


def get_policy_detail_v3(policy_id: str, *, client: Any = None, settings: RetrievalSettings | None = None) -> PolicyDetail | None:
    """승인된 4차 데이터에서 정책 하나를 찾아 상세 정보를 만든다. 없으면 None (API 는 404)."""
    from src.retrieval import grouped_search

    settings = settings or load_settings()
    if settings.mode != "v3":
        raise RetrievalConfigError("get_policy_detail_v3 는 v3 모드에서만 씁니다.")
    client = client if client is not None else grouped_search._client_for(settings.qdrant_url)
    grouped_search._ensure_verified(client, settings)
    points, offset = [], None
    for _ in range(8):   # 한 정책의 청크는 많아야 몇 개다. 다음 쪽이 있으면 끝까지 받는다.
        page, offset = client.scroll(
            collection_name=settings.collection,
            scroll_filter=grouped_search._filter(settings, record_type="policy", policy_id=policy_id),
            limit=64, offset=offset, with_payload=True, with_vectors=False,
        )
        points += list(page)
        if offset is None:
            break
    else:
        raise RetrievalConfigError(f"정책 청크를 끝까지 받지 못했습니다: {policy_id}")
    chunks = []
    for point in points:
        payload = getattr(point, "payload", None) or {}
        md = payload.get("metadata") or {}
        if md.get("data_version") != settings.data_version or md.get("release_status") != V3_RELEASE_STATUS:
            raise RetrievalConfigError(f"승인되지 않았거나 다른 버전의 자료가 조회됐습니다: {md.get('chunk_id')}")
        if md.get("policy_id") == policy_id and md.get("record_type") == "policy":
            chunks.append((str(md.get("chunk_id") or ""), str(payload.get("page_content") or ""), md))
    if not chunks:
        return None
    chunks.sort(key=lambda c: c[0])
    md = chunks[0][2]
    for _, _, other in chunks[1:]:
        differs = [k for k in _SAME_ACROSS_CHUNKS if other.get(k) != md.get(k)]
        if differs:
            raise RetrievalConfigError(f"같은 정책의 청크인데 메타데이터가 다릅니다: {policy_id} {differs}")
    # 청크 번호가 1부터 빠짐없이 이어지고, 이어 붙인 본문이 끝 라벨까지 있어야 온전한 본문으로 본다.
    numbers = [int(m.group(1)) if (m := _CHUNK_NO_RE.search(c[0])) else -1 for c in chunks]
    body = merge_chunks([c[1] for c in chunks]) if numbers == list(range(1, len(chunks) + 1)) else None
    sections = parse_sections(body) if body else {}
    if END_LABEL not in sections:
        body, sections = None, {}

    keys = list(md.get("applies_to_keys") or [])
    sido, sigungu = _region_names(keys)
    unknown_scope = not keys
    badges = [Badge(label="원본 정보", tone="info"),
              Badge(label="적용 지역 미확인", tone="warn") if unknown_scope else Badge(label="적용 지역 후보", tone="info")]
    contacts, contact_note = split_contacts(md)
    end_date = md.get("end_date")
    application = sections.get("신청 방법")
    if application and sections.get("신청 방식"):
        application = f"{application} (신청 방식: {sections['신청 방식']})"

    return PolicyDetail(
        policy_id=policy_id,
        title=str(md.get("title") or sections.get("사업명") or "정책명 확인 필요"),
        summary=sections.get("사업 개요"),
        sido_name=sido, sigungu_name=sigungu,
        badges=badges,
        target_text=sections.get("지원 대상"),
        selection_criteria_text=sections.get("선정 기준"),
        benefit_text=sections.get("지원 내용"),
        application_text=application,
        department=md.get("department"),
        contacts=contacts, contact_note=contact_note,
        source_url=_valid_url(md.get("source_url")),
        start_date=md.get("start_date"),
        end_date=None if end_date == OPEN_END_DATE else end_date,
        applies_to=keys,
        scope_status=md.get("scope_status"),
        registered_sido=md.get("sido_name") if unknown_scope else None,
        # 청크를 정확히 이어 붙이지 못했으면 본문 칸을 비우고 그 사실을 알린다.
        body_incomplete=body is None,
    )
