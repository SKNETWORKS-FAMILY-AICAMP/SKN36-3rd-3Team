"""검색 공통 설정 (B1). 아직 기존 검색 코드에 연결하지 않았다. B2부터 단계적으로 쓴다.

환경 변수
- RAG_RETRIEVAL_MODE : legacy_v1(3차 방식) | v3(4차 데이터·묶음별 검색). 적지 않으면 legacy_v1.
                       적지 않아서 legacy_v1 이 된 것인지는 mode_explicit 로 구분한다.
                       (처음 계획은 "적지 않으면 오류"였다. 지금 서비스에 이 변수가 없어 연결하는 순간 멈추므로
                        과도기 동안만 legacy_v1 로 본다. 연결할 때 mode_explicit 가 거짓이면 경고를 남긴다.
                        적지 않았다고 v3 로 넘어가는 일은 없다.)
- RAG_DATA_VERSION   : v3 에서 필수. 검색할 데이터 버전(예: nationwide_2026_11_26_6efc3b7671b3).
- QDRANT_COLLECTION / QDRANT_COLLECTION_NAME : 같은 뜻의 이름 두 개가 코드에 섞여 있다.
                       하나만 적거나 둘을 같은 값으로 적어야 한다. 서로 다르면 어느 쪽인지 알 수 없어 오류.

v3 모드는 "설정이 맞다"와 "그 컬렉션이 정말 그 버전의 승인된 데이터다"를 따로 확인한다(verify_v3_collection).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

MODES = ("legacy_v1", "v3")
DEFAULT_MODE = "legacy_v1"
# 4차 적재 스크립트(scripts/load_v3_qdrant.py)가 만드는 payload 색인. 묶음별 검색이 이 색인으로 거른다.
V3_REQUIRED_INDEXES = (
    "metadata.record_type", "metadata.applies_to_keys", "metadata.scope_status",
    "metadata.data_version", "metadata.release_status", "metadata.sido_name",
)
V3_RELEASE_STATUS = "approved"
V3_VECTOR_SIZE, V3_DISTANCE, V3_INDEX_TYPE = 1024, "cosine", "keyword"   # KURE-v1, 4차 적재 설정


class RetrievalConfigError(RuntimeError):
    """검색 설정이 비었거나 서로 맞지 않을 때, 또는 검색된 자료가 설정과 맞지 않을 때.

    서버 쪽 문제다. 사용자 입력 오류(ValueError)와 섞이지 않게 RuntimeError 로 둔다
    (API 는 ValueError 를 400, 그 밖의 오류를 503 으로 돌려준다).
    """


@dataclass(frozen=True)
class RetrievalSettings:
    mode: str
    mode_explicit: bool          # RAG_RETRIEVAL_MODE 를 직접 적었는가
    collection: str
    data_version: str | None     # legacy_v1 에서는 없어도 된다
    qdrant_url: str


def _clean(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key) or "").strip()


def resolve_mode(env: Mapping[str, str] | None = None) -> tuple[str, bool]:
    env = os.environ if env is None else env
    raw = _clean(env, "RAG_RETRIEVAL_MODE")
    if not raw:
        return DEFAULT_MODE, False
    if raw not in MODES:
        raise RetrievalConfigError(f"RAG_RETRIEVAL_MODE 는 {', '.join(MODES)} 중 하나여야 합니다: {raw!r}")
    return raw, True


def resolve_collection(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    a, b = _clean(env, "QDRANT_COLLECTION"), _clean(env, "QDRANT_COLLECTION_NAME")
    if a and b and a != b:
        raise RetrievalConfigError(
            f"QDRANT_COLLECTION({a})과 QDRANT_COLLECTION_NAME({b})이 서로 다릅니다. 하나만 적거나 같은 값으로 맞추세요."
        )
    if not (a or b):
        raise RetrievalConfigError("QDRANT_COLLECTION 에 실제 적재된 컬렉션 이름을 적으세요.")
    return a or b


def load_settings(env: Mapping[str, str] | None = None) -> RetrievalSettings:
    """환경 변수에서 검색 설정을 읽는다. DB에 접속하지 않는다."""
    env = os.environ if env is None else env
    mode, explicit = resolve_mode(env)
    data_version = _clean(env, "RAG_DATA_VERSION") or None
    if mode == "v3" and not data_version:
        raise RetrievalConfigError("v3 모드에서는 RAG_DATA_VERSION 이 필요합니다.")
    return RetrievalSettings(
        mode=mode, mode_explicit=explicit, collection=resolve_collection(env), data_version=data_version,
        qdrant_url=_clean(env, "QDRANT_URL") or "http://localhost:6333",
    )


def verify_v3_collection(client: Any, settings: RetrievalSettings) -> dict[str, Any]:
    """v3 모드에서 쓰려는 컬렉션이 그 데이터 버전의 승인된 데이터로만 채워져 있는지 읽기 전용으로 확인한다.

    client 는 qdrant_client.QdrantClient 와 같은 모양(get_collection, count)을 가진 객체.
    문제가 있으면 RetrievalConfigError. 통과하면 확인한 숫자를 돌려준다.
    """
    if settings.mode != "v3":
        raise RetrievalConfigError("verify_v3_collection 은 v3 모드에서만 씁니다.")
    try:
        info = client.get_collection(settings.collection)
    except Exception as exc:
        raise RetrievalConfigError(f"컬렉션을 찾을 수 없습니다: {settings.collection} ({type(exc).__name__})") from exc
    # 벡터 구조: 이름 없는 단일 벡터, 1024차원, 코사인 (다르면 질문 벡터와 비교할 수 없다)
    vectors = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
    size, distance = getattr(vectors, "size", None), getattr(vectors, "distance", None)
    if size != V3_VECTOR_SIZE or _name(distance) != V3_DISTANCE:
        raise RetrievalConfigError(
            f"벡터 구조가 다릅니다 (단일 벡터 {V3_VECTOR_SIZE}차원 {V3_DISTANCE} 여야 함): size={size!r}, distance={_name(distance)!r}"
        )
    schema = getattr(info, "payload_schema", None) or {}
    missing = [name for name in V3_REQUIRED_INDEXES if name not in schema]
    if missing:
        raise RetrievalConfigError(f"v3 검색에 필요한 색인이 없습니다: {missing}")
    wrong_type = [name for name in V3_REQUIRED_INDEXES if _name(getattr(schema[name], "data_type", None)) != V3_INDEX_TYPE]
    if wrong_type:
        raise RetrievalConfigError(f"색인 종류가 {V3_INDEX_TYPE} 가 아닙니다: {wrong_type}")
    total = _count(client, settings.collection, None)
    matched = _count(client, settings.collection, {
        "must": [
            {"key": "metadata.data_version", "match": {"value": settings.data_version}},
            {"key": "metadata.release_status", "match": {"value": V3_RELEASE_STATUS}},
        ]
    })
    if total == 0 or matched != total:
        raise RetrievalConfigError(
            f"컬렉션 {settings.collection} 의 {total}건 중 {matched}건만 데이터 버전 {settings.data_version}·승인 상태입니다."
        )
    return {"collection": settings.collection, "data_version": settings.data_version, "points": total}


def _name(value: Any) -> str:
    """qdrant_client 의 열거형(Distance.COSINE 등)이나 글자를 소문자 이름으로."""
    return str(getattr(value, "value", value) or "").lower()


def _count(client: Any, collection: str, count_filter: dict | None) -> int:
    result = client.count(collection_name=collection, count_filter=count_filter, exact=True)
    return int(getattr(result, "count", result))
