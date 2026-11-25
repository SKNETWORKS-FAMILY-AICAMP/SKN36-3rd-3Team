"""Compare complete snapshots; write a human review queue, never deploy changes."""
import argparse
import csv
import json
from pathlib import Path

from src.welfare_preprocessing.welfare_pipeline.io_utils import read_jsonl, ensure_unique


def meaningful(row):
    # Counters and collection provenance change without a policy change.
    ignored = {'inqNum', 'detail_inqNum', 'data_version', 'source_snapshot_file', 'detail_source_file'}
    return {k: v for k, v in row.items() if k not in ignored}


def compare(before, after):
    old, new = read_jsonl(before), read_jsonl(after)
    ensure_unique(old, 'servId')
    ensure_unique(new, 'servId')
    old_regions = {r.get('requested_region') or r.get('ctpvNm') for r in old}
    new_regions = {r.get('requested_region') or r.get('ctpvNm') for r in new}
    if old_regions != new_regions or None in old_regions:
        raise ValueError('수집 지역이 다릅니다. 일부 지역 누락을 정책 삭제로 해석할 수 없습니다.')
    if not all(r.get('detail_fetched') is True for r in new):
        raise ValueError('새 스냅샷에 상세 미수집 건이 있습니다.')
    old_by_id, new_by_id = ({r['servId']: r for r in rows} for rows in (old, new))
    changes = []
    for pid in sorted(old_by_id.keys() | new_by_id.keys()):
        before_row, after_row = old_by_id.get(pid), new_by_id.get(pid)
        if before_row is None:
            status, fields = 'new', []
        elif after_row is None:
            status, fields = 'missing_in_snapshot_review_before_retirement', []
        else:
            a, b = meaningful(before_row), meaningful(after_row)
            fields = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
            if not fields:
                continue
            status = 'updated'
        row = after_row or before_row
        changes.append({'policy_id': pid, 'change_type': status,
                        'title': row.get('detail_servNm') or row.get('servNm'),
                        'region': row.get('requested_region') or row.get('ctpvNm'),
                        'changed_fields': ', '.join(fields), 'review_status': 'pending'})
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--before', required=True, type=Path)
    ap.add_argument('--after', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args = ap.parse_args()
    changes = compare(args.before, args.after)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['policy_id','change_type','title','region','changed_fields','review_status'])
        writer.writeheader()
        writer.writerows(changes)
    print(json.dumps({'changes':len(changes),'review_queue':str(args.output)},ensure_ascii=False))


if __name__ == '__main__':
    main()
