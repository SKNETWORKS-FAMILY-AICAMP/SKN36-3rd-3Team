"""Read-only Qdrant/Neo4j hybrid retrieval for the SKN36 welfare chatbot.

Modes: vector, graph, hybrid. No PostgreSQL connection or vector re-embedding
of stored chunks. Qdrant query embedding still uses KURE-v1.

Inject search functions in tests to work before databases are available.
"""
from __future__ import annotations

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
) -> dict[str, Any]:
    """Return unified evidence, not an LLM answer.

    `hybrid` = Qdrant semantic search -> Neo4j 1-hop policy expansion.
    `graph`  = standalone keyword graph baseline; no Qdrant dependency.
    `vector` = Qdrant-only retrieval.

    Errors from unavailable DBs propagate rather than silently claiming
    successful empty searches. Client-facing error handling belongs in API.
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 빈 문자열일 수 없습니다.")
    if mode not in ("vector", "graph", "hybrid"):
        raise ValueError("mode는 vector, graph, hybrid 중 하나여야 합니다.")
    if not isinstance(k, int) or not 1 <= k <= 50:
        raise ValueError("k는 1~50 범위의 정수여야 합니다.")

    documents: list[dict[str, Any]] = []
    graph_results: list[dict[str, Any]] = []
    graph_only_results: list[dict[str, Any]] = []

    if mode in ("vector", "hybrid"):
        if qdrant_search is None:
            from .qdrant_retriever import search_qdrant
            qdrant_search = search_qdrant
        documents = qdrant_search(question.strip(), k=k)
        if not isinstance(documents, list):
            raise TypeError("Qdrant 검색 결과는 list[dict]여야 합니다.")

    if mode == "hybrid":
        if neo4j_policy_search is None:
            from .neo4j_retriever import search_neo4j
            neo4j_policy_search = search_neo4j
        # Only policy hits have an existing canonical policy_id.
        # PDF sections must NOT be coerced into arbitrary policy IDs.
        policy_ids = list(dict.fromkeys(
            str(d["policy_id"]) for d in documents
            if isinstance(d, dict) and d.get("record_type") == "policy" and d.get("policy_id")
        ))
        for policy_id in policy_ids:
            graph_results.append(neo4j_policy_search(policy_id))

    if mode == "graph":
        if neo4j_question_search is None:
            from .neo4j_retriever import search_neo4j_only
            neo4j_question_search = search_neo4j_only
        graph_only_results = neo4j_question_search(question.strip(), limit=k)
        if not isinstance(graph_only_results, list):
            raise TypeError("Neo4j 단독 검색 결과는 list[dict]여야 합니다.")

    checked = validate_evidence(documents, graph_results)
    warnings = list(checked["warnings"])
    if mode == "graph":
        warnings.append("Neo4j 단독 검색은 키워드 기반 초기 베이스라인이며, 관계 근거·출처는 별도 확인 필요")
    return {
        "question": question.strip(),
        "mode": mode,
        "documents": checked["documents"],
        "graph_results": checked["graph_results"],
        "graph_only_results": graph_only_results,
        "has_evidence": checked["has_evidence"] or bool(graph_only_results),
        "verification_level": checked["verification_level"],
        "warnings": warnings,
    }


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("question", help="복지정책 질문")
    parser.add_argument("--mode", choices=["vector", "graph", "hybrid"], default="hybrid")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(retrieve_welfare(args.question, args.mode, args.k), ensure_ascii=False, indent=2))
