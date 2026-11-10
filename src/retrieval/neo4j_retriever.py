"""Read-only Neo4j retrieval for elderly-welfare Graph RAG.

No PostgreSQL. Works with Neo4j 5/2025 Cypher; does not create indexes or
assume a particular label/relationship name. Inspect actual graph schema first.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    user: str
    password: str
    database: str = "neo4j"

    @classmethod
    def from_env(cls) -> "Neo4jConfig":
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            raise ValueError("NEO4J_PASSWORD가 없습니다. .env에 설정하세요.")
        return cls(uri, user, password, os.getenv("NEO4J_DATABASE", "neo4j"))


def _jsonable(value: Any) -> Any:
    """Convert Neo4j types to JSON-safe values without leaking driver objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (tuple, list, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _normalize_id(value: Any) -> str | None:
    """Normalize graph ID without fabricating equivalence.

    We do NOT strip `local:`; Qdrant/Neo4j ID equality is verified explicitly.
    """
    return str(value).strip() if value is not None and str(value).strip() else None


class Neo4jRetriever:
    def __init__(self, config: Neo4jConfig | None = None, driver: Any = None):
        self.config = config or Neo4jConfig.from_env()
        if driver is None:
            try:
                from neo4j import GraphDatabase
            except ImportError as e:
                raise RuntimeError("pip install neo4j python-dotenv") from e
            self.driver = GraphDatabase.driver(
                self.config.uri,
                auth=(self.config.user, self.config.password),
                connection_timeout=10,
            )
        else:
            self.driver = driver

    def close(self):
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _query(self, cypher: str, **params) -> list[dict]:
        with self.driver.session(database=self.config.database) as session:
            return [dict(record) for record in session.run(cypher, **params)]

    def ping(self) -> dict:
        self.driver.verify_connectivity()
        row = self._query("RETURN 'connected' AS status, 1 AS ok")[0]
        return {"status": row["status"], "database": self.config.database}

    def inspect_schema(self, sample_per_label: int = 2) -> dict:
        """Get actual labels/types/properties and representative policy IDs.

        Useful because a .dump cannot be inspected as a JSON file.
        """
        labels = self._query("CALL db.labels() YIELD label RETURN label ORDER BY label")
        rel_types = self._query(
            "CALL db.relationshipTypes() YIELD relationshipType "
            "RETURN relationshipType ORDER BY relationshipType"
        )
        node_props = self._query(
            "CALL db.schema.nodeTypeProperties() "
            "YIELD nodeLabels, propertyName, propertyTypes "
            "RETURN nodeLabels, propertyName, propertyTypes "
            "ORDER BY nodeLabels, propertyName"
        )
        rel_props = self._query(
            "CALL db.schema.relTypeProperties() "
            "YIELD relType, propertyName, propertyTypes "
            "RETURN relType, propertyName, propertyTypes "
            "ORDER BY relType, propertyName"
        )
        sample = self._query(
            "MATCH (n) WHERE n.policy_id IS NOT NULL "
            "RETURN labels(n) AS labels, toString(n.policy_id) AS policy_id, "
            "keys(n) AS properties LIMIT $limit",
            limit=max(1, min(20, int(sample_per_label) * 5)),
        )
        counts = self._query(
            "MATCH (n) WITH count(n) AS nodes "
            "OPTIONAL MATCH ()-[r]->() "
            "RETURN nodes, count(r) AS relationships"
        )[0]
        return {
            "labels": [r["label"] for r in labels],
            "relationship_types": [r["relationshipType"] for r in rel_types],
            "node_properties": [_jsonable(r) for r in node_props],
            "relationship_properties": [_jsonable(r) for r in rel_props],
            "policy_id_examples": sample,
            "counts": counts,
        }

    def get_policy_relationships(self, policy_id: str, limit: int = 30) -> dict:
        """Find a policy by exact policy_id and return connected 1-hop relations.

        Label-agnostic, so it runs on a restored dump before we know its labels.
        No name-only/fuzzy matches are treated as verified policy relationships.
        """
        pid = _normalize_id(policy_id)
        if not pid:
            raise ValueError("policy_id는 비어 있을 수 없습니다.")
        k = max(1, min(200, int(limit)))
        rows = self._query(
            "MATCH (p) WHERE toString(p.policy_id) = $policy_id "
            "OPTIONAL MATCH (p)-[r]-(other) "
            "RETURN labels(p) AS policy_labels, properties(p) AS policy_properties, "
            "type(r) AS relationship_type, "
            "CASE WHEN r IS NULL THEN null "
            "WHEN startNode(r) = p THEN 'outgoing' ELSE 'incoming' END AS direction, "
            "labels(other) AS related_labels, properties(other) AS related_properties, "
            "properties(r) AS relationship_properties "
            "LIMIT $limit",
            policy_id=pid, limit=k,
        )
        if not rows:
            return {"policy_id": pid, "found": False, "policy": None, "relationships": []}
        first = rows[0]
        relations = [
            {
                "type": r["relationship_type"],
                "direction": r["direction"],
                "related_labels": r["related_labels"],
                "related_properties": _jsonable(r["related_properties"]),
                "relationship_properties": _jsonable(r["relationship_properties"]),
            }
            for r in rows if r.get("relationship_type") is not None
        ]
        return {
            "policy_id": pid,
            "found": True,
            "policy": {
                "labels": first["policy_labels"],
                "properties": _jsonable(first["policy_properties"]),
            },
            "relationships": relations,
        }

    def get_guideline_relationships(
        self, chunk_id: str, limit: int = 5
    ) -> dict:
        """PDF 청크에서 섹션 및 원본 문서를 조회한다."""
        cid = _normalize_id(chunk_id)
        if not cid:
            raise ValueError("chunk_id는 비어 있을 수 없습니다.")

        rows = self._query(
            """
            MATCH (c:RagABFixedChunk {chunk_id: $chunk_id})
                  -[:CHUNK_OF]->(s:RagABSection)
            OPTIONAL MATCH (d:RagABDocument)
                  -[:HAS_SECTION]->(s)
            RETURN
                c.chunk_id AS chunk_id,
                s.section_id AS section_id,
                properties(s) AS section,
                properties(d) AS document
            LIMIT $limit
            """,
            chunk_id=cid,
            limit=max(1, min(20, int(limit))),
        )

        if not rows:
            return {
                "chunk_id": cid,
                "found": False,
                "section_id": None,
                "section": None,
                "document": None,
            }

        row = rows[0]
        return {
            "chunk_id": row["chunk_id"],
            "found": True,
            "section_id": row["section_id"],
            "section": _jsonable(row["section"]),
            "document": _jsonable(row["document"]),
        }

    def search_by_question(self, question: str, limit: int = 5) -> list[dict]:
        """Independent Graph-only baseline, no Qdrant embedding required.

        This is a basic keyword/substring baseline, not a validated final search
        method. It should be improved against actual labels and indexes.
        """
        terms = [v for v in re.findall(r"[가-힣A-Za-z0-9]{2,}", question or "") if len(v) >= 2]
        # Prevent unbounded scan on empty/noisy input; cap terms.
        terms = list(dict.fromkeys(terms))[:8]
        if not terms:
            return []
        k = max(1, min(30, int(limit)))
        rows = self._query(
            "MATCH (n) "
            "WHERE any(key IN ['title','name','policy_name','service_name','target','benefit','description','text'] "
            "  WHERE n[key] IS NOT NULL AND any(term IN $terms "
            "    WHERE toLower(toString(n[key])) CONTAINS toLower(term))) "
            "WITH n, size([term IN $terms WHERE any(key IN "
            "  ['title','name','policy_name','service_name','target','benefit','description','text'] "
            "  WHERE n[key] IS NOT NULL AND toLower(toString(n[key])) CONTAINS toLower(term))]) AS matched_terms "
            "RETURN labels(n) AS labels, properties(n) AS properties, "
            "matched_terms ORDER BY matched_terms DESC LIMIT $limit",
            terms=terms, limit=k,
        )
        return [{"labels": r["labels"], "properties": _jsonable(r["properties"]),
                 "matched_terms": r["matched_terms"]} for r in rows]


def search_neo4j(policy_id: str, limit: int = 30) -> dict:
    """Simple one-call interface used by the hybrid retriever."""
    with Neo4jRetriever() as retriever:
        return retriever.get_policy_relationships(policy_id, limit=limit)


def search_neo4j_only(question: str, limit: int = 5) -> list[dict]:
    """Independent graph-only keyword baseline for comparative testing."""
    with Neo4jRetriever() as retriever:
        return retriever.search_by_question(question, limit=limit)


def main():
    parser = argparse.ArgumentParser(description="Read-only Neo4j Graph RAG inspection/search")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ping")
    sub.add_parser("inspect")
    p = sub.add_parser("policy")
    p.add_argument("policy_id")
    q = sub.add_parser("question")
    q.add_argument("question")
    a = parser.parse_args()
    try:
        with Neo4jRetriever() as retriever:
            result = (retriever.ping() if a.command == "ping" else
                      retriever.inspect_schema() if a.command == "inspect" else
                      retriever.get_policy_relationships(a.policy_id) if a.command == "policy" else
                      retriever.search_by_question(a.question))
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        parser.exit(1, f"Neo4j 조회 실패: {exc}\n")


def search_neo4j_guideline(chunk_id: str, limit: int = 5) -> dict:
    """Qdrant에서 검색한 PDF 청크의 Neo4j 관계를 조회한다."""
    with Neo4jRetriever() as retriever:
        return retriever.get_guideline_relationships(
            chunk_id, limit=limit
        )


if __name__ == "__main__":
    main()



