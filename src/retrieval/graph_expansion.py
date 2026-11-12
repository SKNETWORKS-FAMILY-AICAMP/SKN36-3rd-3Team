"""ABC C안: 검수된 정책 관계를 이용한 Neo4j 확장 (v1).

- 기본 동작은 읽기 전용. 기존 CHUNK_OF/HAS_SECTION 관계를 정책 간 연결로 오인하지 않음.
- 별도 승인된 RELATED_POLICY_REVIEWED 관계가 있어야 새 정책을 반환함.
- qdrant_search.embed_query() 또는 임베딩 재생성을 전혀 수행하지 않음.
- 기존 A안 결과와 합치는 로직은 evaluation notebook에 둔다.

사용 예: from graph_expansion import expand, relation_stats
      expand(["local:WLF00000696"], "서울특별시", "마포구")
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def _driver():
    try:
        from dotenv import load_dotenv
        # 노트북의 현재 작업 위치가 어디든 프로젝트 루트 .env를 탐색.
        for base in [Path.cwd(), Path(__file__).resolve().parent]:
            for folder in [base, *base.parents]:
                env_path = folder / '.env'
                if env_path.is_file():
                    load_dotenv(env_path, override=False)
                    break
    except ImportError:
        pass
    from neo4j import GraphDatabase
    password = os.getenv('NEO4J_PASSWORD')
    if not password:
        raise RuntimeError('NEO4J_PASSWORD가 없습니다. 프로젝트 .env 파일을 확인하세요.')
    driver = GraphDatabase.driver(
        os.getenv('NEO4J_URI', 'bolt://localhost:7687'),
        auth=(os.getenv('NEO4J_USER', 'neo4j'), password),
    )
    driver.verify_connectivity()
    return driver


# 기등록된 정책 간 관계만 검색한다. 기존 CHUNK_OF는 청크 소속 관계일 뿐
# 관련 정책에 대한 추천/동일 자격 조건 관계가 아니라서 제외한다.
EXPANSION_CYPHER = '''
UNWIND $seed_ids AS seed_id
MATCH (seed)
WHERE seed.policy_id = seed_id AND NOT seed:RagABFixedChunk
MATCH (seed)-[rel:RELATED_POLICY_REVIEWED]-(target)
WHERE target.policy_id IS NOT NULL
  AND target.policy_id <> seed_id
  AND coalesce(rel.approved, false) = true
  AND rel.evidence_source IS NOT NULL
MATCH (c:RagABFixedChunk)-[:CHUNK_OF]->(target)
WHERE c.record_type = 'policy'
  AND ($sido IS NULL OR c.sido_name IS NULL OR c.sido_name = $sido)
  AND ($sigungu IS NULL OR c.sigungu_name IS NULL OR c.sigungu_name = $sigungu)
WITH target, c, rel, count(DISTINCT seed_id) AS shared_seed_count
RETURN target.policy_id AS parent_id,
       c.chunk_id AS chunk_id,
       c.record_type AS record_type,
       coalesce(c.title, target.title) AS title,
       c.text AS text,
       c.sido_name AS sido_name,
       c.sigungu_name AS sigungu_name,
       rel.evidence_source AS evidence_source,
       shared_seed_count
ORDER BY shared_seed_count DESC, parent_id, chunk_id
LIMIT $candidate_limit
'''


def relation_stats() -> dict[str, int]:
    """현재 그래프가 관계 확장 가능한 상태인지 확인."""
    cypher = '''
    MATCH ()-[r]->()
    RETURN type(r) AS relation, count(r) AS total
    ORDER BY total DESC
    '''
    with _driver().session(database=os.getenv('NEO4J_DATABASE', 'neo4j')) as session:
        return {r['relation']: r['total'] for r in session.run(cypher)}


def expand(
    parent_ids: list[str],
    sido: str | None = None,
    sigungu: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """기존 검색의 정책 ID에서 출발해 *검수된* 다른 정책을 탐색.

    returns: [{parent_id, chunk_id, title, text, score, source, ...}, ...]
    현재 DB에 검수된 정책 관계가 없다면 [] 반환(정상, 미구현 상태 표시).
    score는 검색 유사도가 아닌 그래프 근거 개수 기반의 표시용 값.
    A와 점수를 직접 비교하여 정렬하지 말 것.
    """
    seeds = list(dict.fromkeys(str(v).strip() for v in (parent_ids or []) if v))
    if not seeds or limit <= 0:
        return []
    with _driver().session(database=os.getenv('NEO4J_DATABASE', 'neo4j')) as session:
        rows = session.run(
            EXPANSION_CYPHER,
            seed_ids=seeds,
            sido=sido or None,
            sigungu=sigungu or None,
            candidate_limit=max(int(limit) * 5, int(limit)),
        ).data()
    seen: set[str] = set(seeds)
    out = []
    for r in rows:
        pid = r.get('parent_id')
        if not pid or pid in seen or not r.get('text'):
            continue
        seen.add(pid)
        out.append({
            'parent_id': pid,
            'chunk_id': r.get('chunk_id'),
            'record_type': r.get('record_type'),
            'title': r.get('title'),
            'text': r['text'],
            'sido_name': r.get('sido_name'),
            'sigungu_name': r.get('sigungu_name'),
            'score': float(r.get('shared_seed_count') or 0),
            'source': 'graph',
            'evidence_source': r.get('evidence_source'),
        })
        if len(out) >= limit:
            break
    return out


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Neo4j C안 관계 점검 및 확장 테스트')
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--parent-id', action='append', default=[])
    parser.add_argument('--sido')
    parser.add_argument('--sigungu')
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(
        relation_stats() if args.inspect else expand(args.parent_id, args.sido, args.sigungu, args.limit),
        ensure_ascii=False, indent=2,
    ))
