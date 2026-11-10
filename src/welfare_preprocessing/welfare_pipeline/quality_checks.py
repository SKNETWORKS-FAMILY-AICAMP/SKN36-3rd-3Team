"""선택적 STEP 1 점검: API 원본 및 정규화 파일의 건수/누락/중복."""
from collections import Counter
from .io_utils import read_jsonl

def report(path,id_field='policy_id'):
    rows=read_jsonl(path)
    ids=[str(r.get(id_field) or '').strip() for r in rows]
    return {'count':len(rows),'duplicate_ids':len(ids)-len(set(ids)),
            'missing_ids':sum(not x for x in ids),
            'detail_fetched_true':sum(str(r.get('detail_fetched')).lower()=='true' for r in rows),
            'missing_title':sum(not str(r.get('title') or r.get('servNm') or '').strip() for r in rows),
            'regions':dict(Counter(str(r.get('requested_region')) for r in rows))}
