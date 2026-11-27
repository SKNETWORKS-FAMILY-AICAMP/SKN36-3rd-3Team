"""묶음별 검색 (B2). 4차(v3) 모드에서만 쓴다. 아직 에이전트·API 에 연결하지 않았다(B3·B4).

3차 방식은 지역 구분 없이 전체에서 상위 몇 개를 뽑은 뒤 지역을 걸러서, 전국 PDF에 밀려 지역 정책이 남지 않는 일이 많았다.
여기서는 Qdrant 에서 처음부터 묶음마다 따로 찾는다.

  local      : 고른 지역에 적용되는 지역 정책 (답변 근거). 시도만 골랐으면 그 시도 안의 지역 정책 후보.
  national   : 전국 자료 (답변 근거).
  unverified : 고른 시도에 등록됐지만 적용 지역이 확정되지 않은 자료. 답변 근거가 아니라 별도 목록.
  reference  : 전국을 직접 골랐을 때의 지역 정책. 어느 지역 것인지 밝힌 참고 후보.

이 모듈은 후보를 정확히 가져오는 것까지만 한다. 점수로 자르지 않는다. 정책이 없는 지역에서도 무관한 후보가
높은 점수로 나올 수 있으므로, 질문과 관련이 있는지는 뒤의 근거 판정 단계가 본다.
결과가 비었거나 적다고 해서 "정책이 없다"는 뜻은 아니다(info 의 short·dropped 를 함께 본다).
"""
from __future__ import annotations

import collections
import logging
import math
import os
from functools import lru_cache
from typing import Any, Callable

from . import region_rules as R
from .config import RetrievalConfigError, RetrievalSettings, V3_RELEASE_STATUS, V3_VECTOR_SIZE, load_settings, verify_v3_collection

logger = logging.getLogger(__name__)

PAGE = 64                 # Qdrant 에서 한 번에 받는 청크 수
MAX_PAGES = 8             # 목표 개수를 못 채우면 이어서 받는 횟수 한도 (최대 512청크)
MAX_PER_SECTION = 2       # 전국 PDF는 같은 절에서 2개까지 (3차와 같은 규칙)
GROUPS = ("local", "national", "unverified", "reference")
_verified: set[tuple[str, str, str]] = set()   # 점검에 성공한 (서버, 컬렉션, 데이터 버전). 실패는 기억하지 않는다.


@lru_cache(maxsize=4)
def _client_for(url: str) -> Any:
    """설정에 적힌 서버로 접속한다. 점검한 서버와 검색하는 서버가 달라지지 않게, 환경 변수가 아니라 설정값을 쓴다."""
    from qdrant_client import QdrantClient
    return QdrantClient(url=url, api_key=os.getenv("QDRANT_API_KEY") or None, timeout=30)


def _default_embed(question: str) -> list[float]:
    """3차와 같은 모델·판. 문서를 임베딩할 때처럼 줄바꿈은 빈칸으로 바꾼다."""
    from .qdrant_retriever import _embedding_model
    return _embedding_model().encode(question.replace("\n", " "), normalize_embeddings=True, convert_to_numpy=True).tolist()


def _ensure_verified(client: Any, settings: RetrievalSettings) -> None:
    key = (settings.qdrant_url, settings.collection, str(settings.data_version))
    if key not in _verified:
        verify_v3_collection(client, settings)   # 실패하면 RetrievalConfigError 로 검색을 멈춘다.
        _verified.add(key)


def _filter(settings: RetrievalSettings, must_not_unknown: bool = False, **match: str) -> dict[str, Any]:
    """모든 묶음에 데이터 버전·승인 상태 조건을 매번 붙인다 (컬렉션 점검을 통과했더라도)."""
    must = [
        {"key": "metadata.data_version", "match": {"value": settings.data_version}},
        {"key": "metadata.release_status", "match": {"value": V3_RELEASE_STATUS}},
    ]
    must += [{"key": f"metadata.{name}", "match": {"value": value}} for name, value in match.items()]
    flt: dict[str, Any] = {"must": must}
    if must_not_unknown:   # 적용 지역이 정해진 정책 전부 (상태 이름이 candidate 에서 confirmed 로 바뀌어도 빠지지 않게)
        flt["must_not"] = [{"key": "metadata.scope_status", "match": {"value": "unknown"}}]
    return flt


def _doc(hit: Any, group: str) -> dict[str, Any]:
    """Qdrant 결과 하나를 3차 검색(search_qdrant)과 같은 모양의 문서로 바꾸고, 어느 묶음인지 붙인다."""
    payload = getattr(hit, "payload", None) or {}
    md = dict(payload.get("metadata") or {})
    kind = md.get("record_type")
    return {
        "id": str(getattr(hit, "id", "")),
        "chunk_id": md.get("chunk_id"),
        "parent_id": md.get("parent_id"),
        "record_type": kind,
        "policy_id": md.get("policy_id") if kind == "policy" else None,
        "section_id": md.get("section_id") if kind == "guideline" else None,
        "text": payload.get("page_content") or "",
        "score": float(getattr(hit, "score", 0.0)),
        "title": md.get("title"),
        "source_url": md.get("source_url"),
        "metadata": md,
        "evidence_group": group,
        "region_keys": list(md.get("applies_to_keys") or []),
    }


class _PolicyPicker:
    """점수순으로 오는 청크에서 정책마다 첫(가장 점수 높은) 청크만 남긴다."""

    def __init__(self, k: int) -> None:
        self.k, self.seen, self.out = k, set(), []

    def add(self, d: dict) -> None:
        pid = d["policy_id"]
        if pid and pid not in self.seen and len(self.out) < self.k:
            self.seen.add(pid)
            self.out.append(d)


class _SectionPicker:
    """전국 PDF는 같은 절에서 MAX_PER_SECTION 개까지."""

    def __init__(self, k: int) -> None:
        self.k, self.per, self.out = k, collections.Counter(), []

    def add(self, d: dict) -> None:
        sid = d["section_id"] or d["parent_id"] or d["id"]
        if self.per[sid] < MAX_PER_SECTION and len(self.out) < self.k:
            self.per[sid] += 1
            self.out.append(d)


def search_grouped(
    question: str,
    selection: R.RegionSelection,
    *,
    settings: RetrievalSettings | None = None,
    client: Any = None,
    embed: Callable[[str], list[float]] | None = None,
    local_k: int = 5,
    national_k: int = 3,
    unverified_k: int = 3,
    exact: bool = False,
) -> dict[str, Any]:
    """질문을 한 번 임베딩하고, 고른 지역에 맞는 묶음마다 Qdrant 에서 따로 찾는다 (읽기 전용).

    돌려주는 값: {"local": [...], "national": [...], "unverified": [...], "reference": [...], "info": {...}}
    - local_k·national_k·unverified_k 는 조정 전 임시값이다.
    - exact=True 면 근사 검색 대신 전수 비교를 한다(평가용. 느리지만 순위가 정확하다).
    - info.dropped : 필터로 받아 왔지만 지역 규칙과 맞지 않아 뺀 건수. 0 이어야 정상이다.
    - info.short   : 받아 올 수 있는 한도까지 받았는데도 목표 개수를 못 채운 묶음.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 비어 있을 수 없습니다.")
    if not isinstance(selection, R.RegionSelection):
        raise TypeError("selection 은 region_rules.RegionSelection 이어야 합니다.")
    for name, k in (("local_k", local_k), ("national_k", national_k), ("unverified_k", unverified_k)):
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 20:
            raise ValueError(f"{name} 는 1~20 범위의 정수여야 합니다.")
    settings = settings or load_settings()
    if settings.mode != "v3":
        raise RetrievalConfigError("묶음별 검색은 v3 모드에서만 씁니다 (RAG_RETRIEVAL_MODE=v3).")
    client = client if client is not None else _client_for(settings.qdrant_url)
    _ensure_verified(client, settings)
    vector = [float(x) for x in (embed or _default_embed)(question.strip())]
    if len(vector) != V3_VECTOR_SIZE or not all(math.isfinite(x) for x in vector) or sum(x * x for x in vector) < 1e-12:
        # 임베딩 모델 쪽 문제이므로 사용자 입력 오류(ValueError)로 올리지 않는다.
        raise RuntimeError(f"질문 벡터가 잘못됐습니다 (길이 {len(vector)}. {V3_VECTOR_SIZE}차원이고 유한하며 0벡터가 아니어야 함).")

    fetched: dict[str, int] = {}
    dropped: dict[str, int] = {}
    short: list[str] = []

    def collect(group: str, scope: str, make_picker: Callable[[], Any], flt: dict[str, Any]) -> list[dict]:
        """목표 개수를 채우거나 더 받을 것이 없을 때까지 이어서 받는다.

        근사 검색은 쪽을 넘길 때 순서가 달라져 중복·누락이 생길 수 있다. 그래서 첫 쪽으로 모자라면
        순서가 고정되는 전수 비교(exact)로 처음부터 다시 받는다. 같은 포인트가 다시 와도 한 번만 쓴다.
        """
        picker = _collect_once(group, scope, make_picker(), flt, exact, one_page=not exact)
        if picker is None:   # 근사 검색 첫 쪽으로는 모자람
            picker = _collect_once(group, scope, make_picker(), flt, True, one_page=False)
        if dropped.get(group):
            logger.warning("묶음 %s 에서 지역 규칙과 맞지 않는 자료 %d건을 뺐습니다.", group, dropped[group])
        return picker.out

    def _collect_once(group: str, scope: str, picker: Any, flt: dict[str, Any], use_exact: bool, one_page: bool) -> Any:
        fetched[group], dropped_here, seen_ids = 0, 0, set()
        for page in range(1 if one_page else MAX_PAGES):
            response = client.query_points(
                collection_name=settings.collection, query=vector, query_filter=flt, limit=PAGE, offset=page * PAGE,
                with_payload=True, with_vectors=False, search_params={"exact": True} if use_exact else None,
            )
            hits = list(response.points)
            fetched[group] += len(hits)
            for hit in hits:
                d = _doc(hit, group)
                if d["id"] in seen_ids:
                    continue
                seen_ids.add(d["id"])
                md = d["metadata"]
                # 승인되지 않았거나 다른 버전의 자료가 섞여 나오면 설정이나 적재가 잘못된 것이므로 멈춘다.
                if md.get("data_version") != settings.data_version or md.get("release_status") != V3_RELEASE_STATUS:
                    raise RetrievalConfigError(f"승인되지 않았거나 다른 버전의 자료가 검색됐습니다: {d['chunk_id']}")
                # 지역 규칙과 맞지 않는 자료는 쓰지 않고 건수를 남긴다 (평가에서는 0 이어야 한다).
                if R.classify_scope(md, selection) != scope:
                    dropped_here += 1
                    continue
                picker.add(d)
            if len(picker.out) >= picker.k or len(hits) < PAGE:
                break
        else:
            if one_page:
                return None       # 다 채우지 못했고 더 받을 것이 남았다. 전수 비교로 다시 받는다.
            short.append(group)   # 한도까지 받았는데도 못 채움. "정책 없음"으로 읽지 않는다.
        if dropped_here:
            dropped[group] = dropped_here
        return picker

    result: dict[str, Any] = {g: [] for g in GROUPS}
    result["national"] = collect("national", R.NATIONAL, lambda: _SectionPicker(national_k),
                                 _filter(settings, applies_to_keys=R.NATIONAL_KEY))
    if selection.kind == "region":
        result["local"] = collect("local", R.LOCAL, lambda: _PolicyPicker(local_k),
                                  _filter(settings, record_type="policy", applies_to_keys=selection.key))
    elif selection.kind == "sido_only":
        # keyword 색인은 "시도|" 로 시작하는 키를 찾지 못한다. 등록 시도가 같고 적용 지역이 정해진 정책으로 찾는다.
        result["local"] = collect("local", R.LOCAL, lambda: _PolicyPicker(local_k),
                                  _filter(settings, must_not_unknown=True, record_type="policy", sido_name=selection.sido))
    elif selection.kind == "nationwide":
        result["reference"] = collect("reference", R.REFERENCE, lambda: _PolicyPicker(local_k),
                                      _filter(settings, must_not_unknown=True, record_type="policy"))
    if selection.kind in ("region", "sido_only"):
        result["unverified"] = collect("unverified", R.UNVERIFIED, lambda: _PolicyPicker(unverified_k),
                                       _filter(settings, record_type="policy", scope_status="unknown", sido_name=selection.sido))

    result["info"] = {
        "mode": settings.mode, "collection": settings.collection, "data_version": settings.data_version,
        "qdrant_url": settings.qdrant_url, "exact": exact,
        "selection": {"kind": selection.kind, "sido": selection.sido, "sigungu": selection.sigungu},
        "k": {"local": local_k, "national": national_k, "unverified": unverified_k},
        "fetched": fetched, "returned": {g: len(result[g]) for g in GROUPS}, "dropped": dropped, "short": short,
    }
    return result
