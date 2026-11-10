
"""공식 근거로 검수된 정책 간 관계를 Neo4j에 적재한다.

기본은 미리보기. 실제 쓰기는 --apply를 명시해야 한다.
기존 정책 노드끼리만 연결하며 새 정책 노드를 생성하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from neo4j import GraphDatabase


REQUIRED_COLUMNS = {
    "source_policy_id",
    "target_policy_id",
    "evidence_source",
    "approved",
}

CYPHER = """
MATCH (a), (b)
WHERE a.policy_id = $source_id
  AND b.policy_id = $target_id
  AND NOT a:RagABFixedChunk
  AND NOT b:RagABFixedChunk
WITH a, b
LIMIT 1
MERGE (a)-[r:RELATED_POLICY_REVIEWED]->(b)
SET r.approved = true,
    r.evidence_source = $evidence_source,
    r.reviewed_at = datetime()
RETURN a.policy_id AS source_id,
       b.policy_id AS target_id
"""


def validate_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
    )


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError("CSV 헤더가 없습니다.")

        if not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError(
                f"CSV 필수 컬럼: {sorted(REQUIRED_COLUMNS)}"
            )

        rows = []
        seen = set()

        for number, row in enumerate(reader, start=2):
            source_id = row["source_policy_id"].strip()
            target_id = row["target_policy_id"].strip()
            evidence = row["evidence_source"].strip()
            approved = row["approved"].strip().lower()

            if approved not in ("true", "false"):
                raise ValueError(
                    f"{number}행: approved는 true/false만 허용"
                )

            # 검수되지 않은 관계는 적재하지 않는다.
            if approved != "true":
                continue

            if not source_id or not target_id:
                raise ValueError(f"{number}행: 정책 ID 누락")

            if source_id == target_id:
                raise ValueError(f"{number}행: 자기 자신과 연결 불가")

            if not validate_url(evidence):
                raise ValueError(
                    f"{number}행: 공식 근거 HTTPS URL 필요"
                )

            key = (source_id, target_id)

            if key in seen:
                continue

            seen.add(key)

            rows.append({
                "source_id": source_id,
                "target_id": target_id,
                "evidence_source": evidence,
            })

        return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--csv",
        default="data/processed/reviewed_policy_relations.csv",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="검수된 관계를 실제 Neo4j에 저장",
    )
    args = parser.parse_args()

    rows = load_rows(Path(args.csv))

    print(f"승인된 관계 후보: {len(rows)}건")

    if not args.apply:
        print("미리보기 완료. DB 변경 없음.")
        return

    load_dotenv()

    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD가 없습니다.")

    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), password),
    )

    database = os.getenv("NEO4J_DATABASE", "neo4j")

    try:
        with driver.session(database=database) as session:
            # 모든 대상 정책이 존재하는지 먼저 검사한다.
            for row in rows:
                count = session.run(
                    """
                    MATCH (n)
                    WHERE n.policy_id IN [$source_id, $target_id]
                      AND NOT n:RagABFixedChunk
                    RETURN count(DISTINCT n.policy_id) AS found
                    """,
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                ).single()["found"]

                if count != 2:
                    raise ValueError(
                        "Neo4j에 없는 정책 ID: "
                        f"{row['source_id']} / {row['target_id']}"
                    )

            # 검증이 모두 통과한 경우 한 트랜잭션으로 저장
            def write_all(tx):
                for row in rows:
                    record = tx.run(CYPHER, **row).single()
                    if record is None:
                        raise RuntimeError(
                            f"관계 적재 실패: {row}"
                        )

            session.execute_write(write_all)

        print(f"Neo4j 관계 적재 완료: {len(rows)}건")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
