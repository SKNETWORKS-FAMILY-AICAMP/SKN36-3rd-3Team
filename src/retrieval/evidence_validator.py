"""Lightweight, non-LLM evidence checks for Qdrant + Neo4j welfare RAG.

No PostgreSQL is used. IMPORTANT: a well-formed ID does not prove the
underlying welfare entitlement is valid or a PDF-policy link is true.
"""
from __future__ import annotations

from typing import Any


def validate_evidence(
    documents: list[dict[str, Any]],
    graph_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate structural consistency; return usable evidence and warnings.

    Graph relationships are only attached to a document when Neo4j returned
    `found=True` for exactly the same policy_id. PDF-to-policy relation is never
    inferred from semantic similarity. The result does NOT certify eligibility.
    """
    warnings: list[str] = []
    valid_documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, doc in enumerate(documents):
        if not isinstance(doc, dict):
            warnings.append(f"문서 {idx}: 결과가 딕셔너리가 아님")
            continue
        kind = doc.get("record_type")
        cid = doc.get("chunk_id")
        uid = doc.get("id")
        parent = doc.get("parent_id")
        content = doc.get("text")
        if kind not in ("policy", "guideline"):
            warnings.append(f"문서 {idx}: 지원하지 않는 record_type={kind!r}")
            continue
        if not (isinstance(content, str) and content.strip()):
            warnings.append(f"문서 {idx}: 근거 본문 없음")
            continue
        if not (cid and uid and parent):
            warnings.append(f"문서 {idx}: UUID/chunk_id/parent_id 누락")
            continue
        if kind == "policy" and doc.get("policy_id") != parent:
            warnings.append(f"문서 {idx}: policy_id/parent_id 불일치")
            continue
        if kind == "guideline" and doc.get("section_id") != parent:
            warnings.append(f"문서 {idx}: section_id/parent_id 불일치")
            continue
        if str(uid) in seen:
            continue
        seen.add(str(uid))
        valid_documents.append(doc)
        if not doc.get("source_url"):
            warnings.append(f"문서 {idx}: 공식 출처 URL 미확인 (답변에 출처 링크 추정 금지)")

    policy_ids = {str(d["policy_id"]) for d in valid_documents if d["record_type"] == "policy"}
    valid_graph: list[dict[str, Any]] = []
    for idx, graph in enumerate(graph_results or []):
        if not isinstance(graph, dict):
            warnings.append(f"그래프 {idx}: 잘못된 반환 형식")
            continue
        pid = graph.get("policy_id")
        if not graph.get("found") or pid not in policy_ids:
            warnings.append(f"그래프 {idx}: 검색 문서와 매칭되지 않는 정책 ID 또는 미발견: {pid}")
            continue
        valid_graph.append(graph)
        if graph.get("relationships") and not any(
            isinstance(r, dict) and isinstance(r.get("relationship_properties"), dict)
            and any(r["relationship_properties"].get(k) for k in ("source_id", "source_url", "evidence", "section_id"))
            for r in graph["relationships"]
        ):
            warnings.append(f"그래프 {idx}: 엣지별 근거 속성이 확인되지 않음; 확정적인 자격 판정에 사용 금지")

    return {
        "documents": valid_documents,
        "graph_results": valid_graph,
        "has_evidence": bool(valid_documents or valid_graph),
        "warnings": warnings,
        "verification_level": "structural_only",  # not legal/policy eligibility verified
    }
