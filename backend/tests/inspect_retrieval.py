
import json
from collections import Counter

from src.retrieval.hybrid_retriever import retrieve_welfare


def inspect_retrieval(question: str, k: int = 20):
    result = retrieve_welfare(
        question=question,
        mode="hybrid",
        k=k,
    )

    documents = result.get("documents", [])

    print("\n========== 검색 개요 ==========")
    print("질문:", question)
    print("전체 청크:", len(documents))
    print(
        "유형별:",
        dict(Counter(
            d.get("record_type", "unknown")
            for d in documents
        ))
    )

    print("\n========== 검색 결과 ==========")

    for i, doc in enumerate(documents, start=1):
        metadata = doc.get("metadata") or {}

        def get(key):
            return doc.get(key, metadata.get(key))

        print(f"\n[{i}]")
        print("유형:", get("record_type"))
        print("제목:", get("title"))
        print("정책 ID:", get("policy_id"))
        print("문서 ID:", get("document_id"))
        print("청크 ID:", get("chunk_id"))
        print("유사도 점수:", get("score"))
        print("지역:", get("sido_name"), get("sigungu_name"))
        print(
            "내용:",
            str(get("text") or get("content") or "")[:200]
        )

    print("\n========== Neo4j 결과 ==========")
    print("정책 관계:", len(result.get("graph_results", [])))
    print("PDF 관계:", len(result.get("guideline_results", [])))
    print("근거 검증 수준:", result.get("verification_level"))

    return result


if __name__ == "__main__":
    result = inspect_retrieval(
        question="기초연금 신청 방법",
        k=20,
    )

    with open(
        "retrieval_diagnostic.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    print("\n진단 결과 저장 완료")
