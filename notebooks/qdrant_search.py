"""A안(Qdrant) 검색 함수. 01_qdrant_setup.ipynb로 적재한 뒤 사용한다.

    from qdrant_search import search_policies
    search_policies("마포구 사는데 보행기 지원 있어?", "서울특별시", "마포구", k=5)
"""
from functools import lru_cache

COLLECTION_NAME = "welfare_chunks_v1"
KURE_MODEL = "nlpai-lab/KURE-v1"
KURE_REV = "8b418a58414668e75532ed045c22d9ca018ae2b2"   # A/B 테스트와 같은 버전 (바꾸면 안 됨)


@lru_cache(maxsize=1)
def get_embedding():
    """질문 임베딩 모델 (A·B·C 모두 이것만 사용). 처음 실행 때 KURE-v1 약 2.2GB 다운로드"""
    import torch
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(
        model_name=KURE_MODEL,
        model_kwargs={"device": "cuda" if torch.cuda.is_available() else "cpu", "revision": KURE_REV},
        encode_kwargs={"normalize_embeddings": True},
    )


def embed_query(text):
    """질문 → 1024차원 벡터. Neo4j(B안)도 이 함수로 질문을 임베딩한다."""
    return get_embedding().embed_query(text)


@lru_cache(maxsize=1)
def _vectorstore(host="localhost", port=6333):
    from qdrant_client import QdrantClient
    from langchain_qdrant import QdrantVectorStore
    client = QdrantClient(host=host, port=port)
    return QdrantVectorStore(client=client, collection_name=COLLECTION_NAME, embedding=get_embedding())


def region_filter(sido=None, sigungu=None, *, parent_ids=None):
    """기본 지역 필터 또는 명시적으로 요청한 광역 정책의 부모 ID 필터."""
    from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue, IsEmptyCondition, PayloadField

    def match_or_empty(field, value):
        key = f"metadata.{field}"
        return Filter(should=[FieldCondition(key=key, match=MatchValue(value=value)),
                              IsEmptyCondition(is_empty=PayloadField(key=key))])

    if parent_ids is not None:
        return Filter(must=[FieldCondition(key="metadata.parent_id", match=MatchAny(any=parent_ids))])
    if not sido:
        return None
    conditions = [match_or_empty("sido_name", sido)]
    if sigungu:
        conditions.append(match_or_empty("sigungu_name", sigungu))
    return Filter(must=conditions)


def search_policies(question, sido=None, sigungu=None, k=5, vectorstore=None, *, parent_ids=None):
    """공통 결과 모양: [{parent_id, chunk_id, score, text, source="qdrant", ...}]"""
    if parent_ids == []:
        return []
    vs = vectorstore or _vectorstore()
    results = vs.similarity_search_with_score(
        question, k=k, filter=region_filter(sido, sigungu, parent_ids=parent_ids)
    )
    out = []
    for doc, score in results:
        m = doc.metadata
        out.append({
            "parent_id": m.get("parent_id"), "chunk_id": m.get("chunk_id"),
            "record_type": m.get("record_type"), "title": m.get("title"),
            "score": round(float(score), 3), "text": doc.page_content,
            "sido_name": m.get("sido_name"), "sigungu_name": m.get("sigungu_name"),
            "source_url": m.get("source_url"), "page_start": m.get("page_start"), "page_end": m.get("page_end"),
            "source": "qdrant",
        })
    return out
