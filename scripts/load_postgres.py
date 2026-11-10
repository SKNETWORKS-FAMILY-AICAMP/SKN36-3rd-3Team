"""PR #25 + PR #26 data loader. Validate locally before applying to PostgreSQL.

Run from project root:
  python -m scripts.load_postgres --root . --check
  python -m scripts.load_postgres --root . --apply

Dependencies for --apply: psycopg[binary], python-dotenv.
"""
from __future__ import annotations
import argparse
import json
import os
import uuid
from collections import Counter
from datetime import date
from pathlib import Path

EXPECTED = {"policies": 574, "sources": 4, "guidelines": 1189,
            "fixed_policy": 662, "fixed_guideline": 2738,
            "structure_policy": 675, "structure_guideline": 3190}


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    data = []
    with path.open(encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("객체가 아님")
                data.append(row)
            except (ValueError, json.JSONDecodeError) as e:
                raise ValueError(f"{path}:{line_no} 잘못된 JSONL: {e}") from e
    return data


def input_paths(root: Path, policy_path: Path | None = None) -> dict[str, Path]:
    if policy_path:
        policy = policy_path if policy_path.is_absolute() else root / policy_path
    else:
        matches = sorted((root / 'data/processed/local_welfare/elderly_filtered').glob('run_*/policies_elderly_selected.jsonl'))
        if not matches:
            raise FileNotFoundError('PR #25 노인복지 정책 JSONL을 찾지 못했습니다.')
        policy = matches[-1]
    base = root / 'data/rag'
    return {
        'policies': policy,
        'policy_docs': base / 'documents/policy_documents.jsonl',
        'sources': base / 'documents/source_documents.jsonl',
        'guidelines': base / 'documents/guideline_documents.jsonl',
        'fixed_policy': base / 'chunks/A_fixed/policy_chunks.jsonl',
        'fixed_guideline': base / 'chunks/A_fixed/guideline_chunks.jsonl',
        'structure_policy': base / 'chunks/B_structure/policy_chunks.jsonl',
        'structure_guideline': base / 'chunks/B_structure/guideline_chunks.jsonl',
    }


def unique(rows: list[dict], field: str, tag: str) -> set[str]:
    vals = [r.get(field) for r in rows]
    if any(not isinstance(x, str) or not x.strip() for x in vals):
        raise ValueError(f'{tag}: {field} 누락')
    if len(vals) != len(set(vals)):
        raise ValueError(f'{tag}: {field} 중복')
    return set(vals)


def policy_join_key(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        raise ValueError('정책 ID 누락')
    return raw if raw.startswith('local:') else f'local:{raw}'


def load_and_validate(root: Path, policy_path: Path | None = None) -> tuple[dict, dict]:
    paths = input_paths(root, policy_path)
    rows = {k: read_jsonl(path) for k, path in paths.items()}
    unique(rows['policies'], 'policy_id', 'PR25 정책')
    source_policy = {policy_join_key(r['policy_id']): r for r in rows['policies']}
    if len(source_policy) != len(rows['policies']):
        raise ValueError('PR25 정책 ID를 local: 접두어로 변환한 뒤 충돌 발생')
    doc_keys = unique(rows['policy_docs'], 'policy_id', 'PR26 정책 문서')
    if set(source_policy) != doc_keys:
        a = sorted(set(source_policy) - doc_keys)[:5]
        b = sorted(doc_keys - set(source_policy))[:5]
        raise ValueError(f'PR25 ↔ PR26 정책 ID 불일치 (PR25에만: {a}, PR26에만: {b})')
    unique(rows['sources'], 'document_id', '출처 문서')
    unique(rows['guidelines'], 'section_id', 'PDF 섹션')
    source_ids = {r['document_id'] for r in rows['sources']}
    section_ids = {r['section_id'] for r in rows['guidelines']}
    for r in rows['guidelines']:
        meta = r.get('metadata') or {}
        if meta.get('document_id') not in source_ids:
            raise ValueError(f"PDF 섹션 {r['section_id']}에서 출처 문서 누락: {meta.get('document_id')}")
        if not isinstance(r.get('text'), str) or not r['text'].strip():
            raise ValueError(f"PDF 섹션 {r['section_id']} 본문 비어 있음")
    all_uuids, all_chunk_ids = set(), set()
    for name in ('fixed_policy', 'fixed_guideline', 'structure_policy', 'structure_guideline'):
        strategy = 'fixed' if name.startswith('fixed') else 'structure'
        kind = 'policy' if name.endswith('policy') else 'guideline'
        seen = set()
        for r in rows[name]:
            cid = r.get('chunk_id')
            if not isinstance(cid, str) or not cid:
                raise ValueError(f'{name} chunk_id 누락')
            if cid in seen or cid in all_chunk_ids:
                raise ValueError(f'중복 chunk_id: {cid}')
            seen.add(cid)
            all_chunk_ids.add(cid)
            expected_uuid = uuid.uuid5(uuid.NAMESPACE_URL, cid)
            if str(expected_uuid) != str(r.get('id')):
                raise ValueError(f'{name} UUID 규칙 불일치: {cid}')
            if r['id'] in all_uuids:
                raise ValueError(f'중복 UUID: {r["id"]}')
            all_uuids.add(r['id'])
            m = r.get('metadata')
            if not isinstance(m, dict):
                raise ValueError(f'{name}: metadata는 객체여야 함: {cid}')
            parent = r.get('policy_id') if kind == 'policy' else r.get('section_id')
            known = doc_keys if kind == 'policy' else section_ids
            if parent not in known or m.get('parent_id') != parent:
                raise ValueError(f'{name} 부모 ID 누락/불일치: {cid}')
            if m.get('record_type') != kind or m.get('chunk_strategy') != strategy or m.get('chunk_id') != cid:
                raise ValueError(f'{name} 메타데이터 불일치: {cid}')
            if not isinstance(r.get('text'), str) or not r['text'].strip():
                raise ValueError(f'{name}: 빈 청크 {cid}')
    for r in rows['policy_docs']:
        if not isinstance(r.get('text'), str) or not r['text'].strip():
            raise ValueError(f"정책 문서 {r['policy_id']} 본문 비어 있음")
    counts = {k: len(v) for k, v in rows.items()}
    warnings = [f'{k}: 예상 {expected}건, 실제 {counts[k]}건 (파일 버전 확인)' for k, expected in EXPECTED.items() if counts[k] != expected]
    report = {'files': {k: str(v) for k, v in paths.items()},
              'counts': counts, 'rag_chunks_total': len(all_uuids), 'warnings': warnings,
              'id_rule': 'uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)',
              'policy_id_mapping': 'PR25 WLF... -> PR26 local:WLF...'}
    return rows, report


def iso_date(raw):
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise ValueError(f'날짜 형식 오류: {raw!r}') from exc


def policy_payload(pre: dict, doc: dict) -> tuple:
    meta = doc['metadata']
    pid = doc['policy_id']
    original = pre['policy_id'].removeprefix('local:')
    return (pid, original, pre.get('title') or meta.get('title'), pre.get('summary'),
            pre.get('target_text'), pre.get('selection_criteria_text'), pre.get('benefit_text'),
            pre.get('application_text'), pre.get('application_method_name'), pre.get('department'),
            pre.get('contact'), meta.get('sido_name') or pre.get('sido_name'),
            meta.get('sigungu_name') or pre.get('sigungu_name'),
            meta.get('region_code') or pre.get('region_code'),
            meta.get('region_scope') or pre.get('region_scope'),
            pre.get('region_review_status'), bool(pre.get('region_selection_verified')),
            meta.get('elderly_category') or pre.get('elderly_candidate_category'),
            bool(pre.get('elderly_eligibility_verified')), bool(pre.get('detail_fetched')),
            meta.get('source_url') or pre.get('source_url'),
            iso_date(pre.get('start_date')), iso_date(pre.get('end_date')),
            iso_date(pre.get('updated_at_source')), doc['text'], meta, pre)


def apply_to_postgres(root: Path, rows: dict, report: dict, database_url: str) -> dict:
    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError('pip install "psycopg[binary]" python-dotenv 실행 필요') from exc
    schema = (root / 'src/db/schema.sql').read_text(encoding='utf-8')
    policy_docs = {r['policy_id']: r for r in rows['policy_docs']}
    result = {}
    # Single transaction: partial failure rolls back all inserts.
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema)
            stmt = '''INSERT INTO welfare_policies (
              policy_id,source_serv_id,title,summary,target_text,selection_criteria_text,
              benefit_text,application_text,application_method_name,department,contact,
              sido_name,sigungu_name,region_code,region_scope,region_review_status,
              region_selection_verified,elderly_category,elderly_eligibility_verified,
              detail_fetched,source_url,start_date,end_date,updated_at_source,
              rag_text,metadata,preprocessed_raw
            ) VALUES ('''+','.join(['%s']*27)+''') ON CONFLICT (policy_id) DO UPDATE SET
              title=EXCLUDED.title,summary=EXCLUDED.summary,target_text=EXCLUDED.target_text,
              selection_criteria_text=EXCLUDED.selection_criteria_text,benefit_text=EXCLUDED.benefit_text,
              application_text=EXCLUDED.application_text,application_method_name=EXCLUDED.application_method_name,
              department=EXCLUDED.department,contact=EXCLUDED.contact,sido_name=EXCLUDED.sido_name,
              sigungu_name=EXCLUDED.sigungu_name,region_code=EXCLUDED.region_code,
              region_scope=EXCLUDED.region_scope,region_review_status=EXCLUDED.region_review_status,
              region_selection_verified=EXCLUDED.region_selection_verified,
              elderly_category=EXCLUDED.elderly_category,
              elderly_eligibility_verified=EXCLUDED.elderly_eligibility_verified,
              detail_fetched=EXCLUDED.detail_fetched,source_url=EXCLUDED.source_url,
              start_date=EXCLUDED.start_date,end_date=EXCLUDED.end_date,
              updated_at_source=EXCLUDED.updated_at_source,rag_text=EXCLUDED.rag_text,
              metadata=EXCLUDED.metadata,preprocessed_raw=EXCLUDED.preprocessed_raw'''
            for r in rows['policies']:
                pid = policy_join_key(r['policy_id'])
                v = policy_payload(r, policy_docs[pid]);cur.execute(stmt,(*v[:-2],Jsonb(v[-2]),Jsonb(v[-1])))
            result['welfare_policies'] = len(rows['policies'])
            for r in rows['sources']:
                cur.execute('''INSERT INTO source_documents
                    (document_id,title,publisher,publication_year,document_type,source_url,metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (document_id) DO UPDATE SET title=EXCLUDED.title,
                    publisher=EXCLUDED.publisher,publication_year=EXCLUDED.publication_year,
                    document_type=EXCLUDED.document_type,source_url=EXCLUDED.source_url,
                    metadata=EXCLUDED.metadata''',
                    (r['document_id'],r.get('title'),r.get('publisher'),r.get('publication_year'),
                     r.get('document_type'),r.get('source_url'),Jsonb(r)))
            result['source_documents'] = len(rows['sources'])
            for r in rows['guidelines']:
                m=r['metadata']
                cur.execute('''INSERT INTO guideline_sections
                    (section_id,document_id,text_content,page_start,page_end,metadata)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (section_id) DO UPDATE SET document_id=EXCLUDED.document_id,
                    text_content=EXCLUDED.text_content,page_start=EXCLUDED.page_start,
                    page_end=EXCLUDED.page_end,metadata=EXCLUDED.metadata''',
                    (r['section_id'],m['document_id'],r['text'],m.get('page_start'),m.get('page_end'),Jsonb(m)))
            result['guideline_sections'] = len(rows['guidelines'])
            chunk_rows = []
            for key in ('fixed_policy','fixed_guideline','structure_policy','structure_guideline'):
                for r in rows[key]:
                    m=r['metadata']
                    chunk_rows.append((r['id'],r['chunk_id'],m['record_type'],m['parent_id'],
                                       m['chunk_strategy'],r['text'],Jsonb(m)))
            cur.executemany('''INSERT INTO rag_chunks
                (id,chunk_id,record_type,parent_id,chunk_strategy,text_content,metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET chunk_id=EXCLUDED.chunk_id,
                record_type=EXCLUDED.record_type,parent_id=EXCLUDED.parent_id,
                chunk_strategy=EXCLUDED.chunk_strategy,text_content=EXCLUDED.text_content,
                metadata=EXCLUDED.metadata''',chunk_rows)
            result['rag_chunks'] = len(chunk_rows)
            cur.execute('INSERT INTO ingestion_runs (input_summary,result_summary) VALUES (%s,%s)',
                        (Jsonb(report['counts']),Jsonb(result)))
        conn.commit()
    return result


def fetch_counts(database_url: str) -> dict[str,int]:
    import psycopg
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            counts={}
            for table in ('welfare_policies','source_documents','guideline_sections','rag_chunks'):
                cur.execute(f'SELECT COUNT(*) FROM {table}')
                counts[table]=cur.fetchone()[0]
            cur.execute('''SELECT count(*) FROM rag_chunks c
               LEFT JOIN welfare_policies p ON c.parent_id = p.policy_id AND c.record_type='policy'
               LEFT JOIN guideline_sections g ON c.parent_id = g.section_id AND c.record_type='guideline'
               WHERE (c.record_type='policy' AND p.policy_id IS NULL)
                  OR (c.record_type='guideline' AND g.section_id IS NULL)''')
            counts['orphan_chunks']=cur.fetchone()[0]
            return counts


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',type=Path,default=Path.cwd())
    ap.add_argument('--policy-path',type=Path,default=None)
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true',help='DB 없이 파일 검증만')
    mode.add_argument('--apply',action='store_true',help='DB에 테이블 생성 및 UPSERT')
    args=ap.parse_args()
    root=args.root.resolve()
    rows,report=load_and_validate(root,args.policy_path)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.apply:
        from dotenv import load_dotenv
        load_dotenv(root/'.env')
        url=os.environ.get('DATABASE_URL')
        if not url:
            raise RuntimeError('프로젝트 루트의 .env에 DATABASE_URL을 설정하세요')
        result=apply_to_postgres(root,rows,report,url)
        print('적재 완료:',result)
        print('DB 검증:',fetch_counts(url))
    else:
        print('CHECK OK: DB에는 아무것도 쓰지 않았습니다.')

if __name__=='__main__':
    main()
