"""Qdrant search adapter for SKN36 welfare Hybrid RAG.

Input : natural-language Korean question.
Output: standardized evidence rows with Qdrant point UUID and source IDs.

Does NOT require PostgreSQL or Neo4j. The latter can consume policy_id.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

load_dotenv()

KURE_MODEL = "nlpai-lab/KURE-v1"
KURE_REVISION = "8b418a58414668e75532ed045c22d9ca018ae2b2"
VECTOR_DIM = 1024


@lru_cache(maxsize=1)
def _embedding_model():
    from sentence_transformers import SentenceTransformer

    # Pin to the exact revision used by the team's A/B experiment.
    return SentenceTransformer(KURE_MODEL, revision=KURE_REVISION)


@lru_cache(maxsize=1)
def _client() -> QdrantClient:
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    key = os.getenv("QDRANT_API_KEY") or None
    return QdrantClient(url=url, api_key=key, timeout=30)


def _collection_name() -> str:
    name = os.getenv("QDRANT_COLLECTION", "").strip()
    if not name:
        raise ValueError(".env의 QDRANT_COLLECTION에 실제 적재된 컬렉션 이름을 입력하세요.")
    return name


def list_collections() -> list[str]:
    """Check the *running* Qdrant, not just GitHub notebook settings."""
    return [c.name for c in _client().get_collections().collections]


def check_collection() -> dict[str, Any]:
    name = _collection_name()
    info = _client().get_collection(name)
    vectors = info.config.params.vectors
    # Single-vector config expected; multi-vector would need an explicit name.
    dim = getattr(vectors, "size", None)
    if dim is not None and dim != VECTOR_DIM:
        raise ValueError(f"컬렉션 차원 {dim} != KURE-v1 {VECTOR_DIM}; 모델과 컬렉션을 확인하세요.")
    return {"collection": name, "points_count": info.points_count, "vector_size": dim}


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Support nested metadata and the flattened metadata seen in notebooks."""
    meta = payload.get("metadata")
    result = dict(meta) if isinstance(meta, dict) else {}
    for k, v in payload.items():
        if k not in ("metadata", "text", "page_content") and k not in result:
            result[k] = v
    return result


def _normalize_hit(hit: Any) -> dict[str, Any]:
    payload = hit.payload or {}
    md = _metadata(payload)
    kind = md.get("record_type")
    parent_id = md.get("parent_id")
    # In the team's PR26 JSONL, policy parent_id is the canonical local:WLF...
    # and guideline parent_id is the guideline section ID.
    policy_id = md.get("policy_id") or (parent_id if kind == "policy" else None)
    section_id = md.get("section_id") or (parent_id if kind == "guideline" else None)
    text = payload.get("text") or payload.get("page_content") or md.get("text") or ""
    return {
        "id": str(hit.id),
        "chunk_id": md.get("chunk_id"),
        "parent_id": parent_id,
        "record_type": kind,
        "policy_id": policy_id,
        "section_id": section_id,
        "text": text,
        "score": float(hit.score),
        "title": md.get("title") or md.get("policy_name") or md.get("source_name"),
        "source_url": md.get("source_url") or md.get("url"),
        "metadata": md,
    }


def search_qdrant(question: str, k: int = 5) -> list[dict[str, Any]]:
    """Embed a Korean question with the winning KURE-v1 model and search Qdrant.

    No region filter is applied yet. PDF metadata can lack region values;
    naive filters may incorrectly remove national/PDF evidence.
    """
    if not question or not question.strip():
        raise ValueError("question은 비어 있을 수 없습니다.")
    if not 1 <= k <= 50:
        raise ValueError("k는 1~50 사이여야 합니다.")
    name = _collection_name()
    embedding = _embedding_model().encode(
        question.strip(), normalize_embeddings=True, convert_to_numpy=True
    )
    vector = embedding.tolist()
    if len(vector) != VECTOR_DIM:
        raise ValueError(f"질문 임베딩 차원 불일치: {len(vector)}")
    response = _client().query_points(
        collection_name=name,
        query=vector,
        limit=k,
        with_payload=True,
        with_vectors=False,
    )
    return [_normalize_hit(hit) for hit in response.points]


if __name__ == "__main__":
    import json

    print("Qdrant 컬렉션 목록:", list_collections())
    print("선택 컬렉션:", check_collection())
    rows = search_qdrant("혼자 사는 어르신이 받을 수 있는 돌봄 서비스는?", k=3)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
