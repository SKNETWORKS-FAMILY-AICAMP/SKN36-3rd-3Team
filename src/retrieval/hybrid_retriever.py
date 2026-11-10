
"""Read-only Qdrant/Neo4j hybrid retrieval for the SKN36 welfare chatbot.

Modes:
    vector: Qdrant semantic retrieval only
    graph: Neo4j keyword graph baseline
    hybrid: Qdrant + Neo4j policy/PDF relationships
            + optional reviewed policy expansion

Stored vectors are never re-embedded.
Question embedding uses KURE-v1.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Literal

from .evidence_validator import validate_evidence

Mode = Literal["vector", "graph", "hybrid"]


def retrieve_welfare(
    question: str,
    mode: Mode = "hybrid",
    k: int = 5,
    *,
    qdrant_search: Callable[..., list[dict[str, Any]]] | None = None,
    neo4j_policy_search: Callable[..., dict[str, Any]] | None = None,
    neo4j_question_search: Callable[..., list[dict[str, Any]]] | None = None,
    neo4j_guideline_search: Callable[..., dict[str, Any]] | None = None,
    graph_expansion_search: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Return unified retrieval evidence without generating an LLM answer.

    Approved graph expansion is optional and disabled by default.
    Database failures propagate to the API layer.
    """

    # 1. 입력 검증
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 빈 문자열일 수 없습니다.")

    if mode not in ("vector", "graph", "hybrid"):
        raise ValueError("mode는 vector, graph, hybrid 중 하나여야 합니다.")

    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 50:
        raise ValueError("k는 1~50 범위의 정수여야 합니다.")

    question = question.strip()

    # 2. 결과 초기화
    documents: list[dict[str, Any]] = []
    graph_results: list[dict[str, Any]] = []
    graph_only_results: list[dict[str, Any]] = []
    guideline_results: list[dict[str, Any]] = []
    expanded_results: list[dict[str, Any]] = []
    policy_ids: list[str] = []

    # 3. Qdrant 벡터 검색
    if mode in ("vector", "hybrid"):
        if qdrant_search is None:
            from .qdrant_retriever import search_qdrant
            qdrant_search = search_qdrant

        documents = qdrant_search(question, k=k)

        if not isinstance(documents, list):
            raise TypeError("Qdrant 검색 결과는 list[dict]여야 합니다.")

    # 4. Hybrid 검색
    if mode == "hybrid":

        if neo4j_policy_search is None:
            from .neo4j_retriever import search_neo4j
            neo4j_policy_search = search_neo4j

        if neo4j_guideline_search is None:
            from .neo4j_retriever import search_neo4j_guideline
            neo4j_guideline_search = search_neo4j_guideline

        # 4-1. 정책 청크의 policy_id 수집 (중복 제거)
        policy_ids = list(dict.fromkeys(
            str(doc["policy_id"])
            for doc in documents
            if isinstance(doc, dict)
            and doc.get("record_type") == "policy"
            and doc.get("policy_id")
        ))

        # 4-2. Neo4j 정책 관계 검색
        for policy_id in policy_ids:
            result = neo4j_policy_search(policy_id)
            graph_results.append(result)

        # 4-3. PDF 청크 수집
        guideline_docs = [
            doc
            for doc in documents
            if isinstance(doc, dict)
            and doc.get("record_type") == "guideline"
            and doc.get("chunk_id")
        ]

        seen_chunks: set[str] = set()

        # 4-4. PDF 청크 -> 섹션 -> 원본 문서 조회
        for doc in guideline_docs:
            chunk_id = str(doc["chunk_id"])

            if chunk_id in seen_chunks:
                continue

            seen_chunks.add(chunk_id)

            result = neo4j_guideline_search(chunk_id)

            # 실제 PDF 청크와 섹션 ID가 일치하는지 검증
            if (
                isinstance(result, dict)
                and result.get("found")
                and str(result.get("chunk_id")) == chunk_id
                and result.get("section_id") == doc.get("section_id")
            ):
                guideline_results.append(result)

        # 4-5. 승인된 정책 관계를 이용한 추가 검색
        # 기본값 false: 기존 Hybrid 검색 동작 유지
        expansion_enabled = (
            os.getenv(
                "ENABLE_REVIEWED_GRAPH_EXPANSION", "false"
            ).strip().lower() == "true"
        )

        if expansion_enabled and policy_ids:

            if graph_expansion_search is None:
                from .graph_expansion import expand
                graph_expansion_search = expand

            expanded_results = graph_expansion_search(
                parent_ids=policy_ids,
                limit=k,
            )

            if not isinstance(expanded_results, list):
                raise TypeError(
                    "정책 관계 확장 결과는 list[dict]여야 합니다."
                )

            # 기존 정책 자체가 확장 결과에 중복 포함되지 않도록 방지
            seed_ids = set(policy_ids)
            seen_expanded: set[str] = set()
            filtered_results = []

            for item in expanded_results:
                if not isinstance(item, dict):
                    continue

                parent_id = str(item.get("parent_id") or "")

                if not parent_id or parent_id in seed_ids:
                    continue

                if parent_id in seen_expanded:
                    continue

                if not item.get("evidence_source"):
                    continue

                if not item.get("text"):
                    continue

                seen_expanded.add(parent_id)
                filtered_results.append(item)

            expanded_results = filtered_results[:k]

    # 5. Neo4j 단독 검색 (비교용 baseline)
    if mode == "graph":

        if neo4j_question_search is None:
            from .neo4j_retriever import search_neo4j_only
            neo4j_question_search = search_neo4j_only

        graph_only_results = neo4j_question_search(
            question,
            limit=k,
        )

        if not isinstance(graph_only_results, list):
            raise TypeError(
                "Neo4j 단독 검색 결과는 list[dict]여야 합니다."
            )

    # 6. 기존 검색 근거 구조 검증
    checked = validate_evidence(
        documents,
        graph_results,
    )

    warnings = list(checked["warnings"])

    if mode == "graph":
        warnings.append(
            "Neo4j 단독 검색은 키워드 기반 초기 베이스라인이며, "
            "관계 근거·출처는 별도 확인 필요"
        )

    if expanded_results:
        warnings.append(
            "Neo4j 정책 확장 결과는 관계 근거가 있는 후보이며, "
            "실제 신청 자격 및 정책 최신성 검증이 필요합니다."
        )

    # 7. 통합 검색 결과 반환
    # graph_expansion_results는 별도 후보로 유지한다.
    # 아직 검증된 원본 documents와 자동 병합하지 않는다.
    return {
        "question": question,
        "mode": mode,

        # Qdrant에서 검증한 정책/PDF 청크
        "documents": checked["documents"],

        # Neo4j 기존 정책 관계
        "graph_results": checked["graph_results"],

        # Neo4j PDF 섹션 및 원본 문서 관계
        "guideline_results": guideline_results,

        # Neo4j 단독 검색 결과
        "graph_only_results": graph_only_results,

        # 승인된 정책 관계로 확장된 후보
        "graph_expansion_results": expanded_results,

        "has_evidence": (
            checked["has_evidence"]
            or bool(graph_only_results)
            or bool(guideline_results)
        ),

        "verification_level": checked["verification_level"],
        "warnings": warnings,
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("question", help="복지정책 질문")
    parser.add_argument(
        "--mode",
        choices=["vector", "graph", "hybrid"],
        default="hybrid",
    )
    parser.add_argument("--k", type=int, default=5)

    args = parser.parse_args()

    result = retrieve_welfare(
        args.question,
        mode=args.mode,
        k=args.k,
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
