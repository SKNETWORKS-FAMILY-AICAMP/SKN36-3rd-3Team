"""Build an isolated RAG candidate from the validated PR #36 staging input.

From repository root: python -m scripts.build_local_welfare_candidate --output-dir /tmp/welfare-candidates
This does not write to PostgreSQL, Qdrant or Neo4j.
"""
import argparse
from hashlib import sha256
import json
import shutil
from pathlib import Path

from src.welfare_preprocessing.welfare_pipeline import (
    normalize_policies, region_candidates, region_selection, elderly_filter,
)
from src.welfare_preprocessing.welfare_pipeline.io_utils import read_jsonl, write_jsonl, ensure_unique, new_run_dir
from src.rag.run_step05 import run as build_docs
from src.rag.chunking.run_step07 import build as build_chunks
from scripts.load_postgres import load_and_validate


STAGING = Path('data/staging/local_welfare/2026-11-25')


def validate_input(root: Path, source: Path, validation_report: Path) -> tuple[list[dict], dict]:
    report = json.loads(validation_report.read_text(encoding='utf-8'))
    info = next((item for item in report.get('outputs', [])
                 if root / item.get('path', '') == source), None)
    raw = source.read_bytes()
    actual_sha = sha256(raw).hexdigest()
    if not info:
        raise ValueError('PR #36 검증 보고서에서 통합 원본 경로를 찾지 못했습니다')
    if actual_sha == info.get('sha256'):
        line_ending = 'as_reported'
    elif (b'\r' not in raw and info.get('bytes') == len(raw) + raw.count(b'\n')
          and sha256(raw.replace(b'\n', b'\r\n')).hexdigest() == info.get('sha256')):
        # PR #36 uploaded CRLF JSONL, which Git stored with LF line endings.
        line_ending = 'git_normalized_crlf_to_lf'
    else:
        raise ValueError('PR #36 검증 보고서와 통합 원본 SHA-256 불일치')
    rows = read_jsonl(source)
    ensure_unique(rows, 'servId')
    if len(rows) != info['rows'] or not all(row.get('detail_fetched') is True for row in rows):
        raise ValueError('통합 원본 건수/상세 플래그 불일치')
    return rows, {'path': str(source), 'sha256': actual_sha,
                  'report_sha256': info['sha256'], 'line_ending': line_ending,
                  'rows': len(rows), 'data_version': info['sha256'][:16]}


def build(root: Path, output_dir: Path) -> dict:
    source = root / STAGING / 'merged_policies_raw.jsonl'
    source_rows, snapshot = validate_input(root, source, root / STAGING / 'validation_report.json')
    stage = new_run_dir(output_dir)
    snapshot['known_missing_regions'] = ['광주광역시', '전라남도']
    snapshot['legacy_jeonnam_pending_path'] = str(root / STAGING / 'legacy_jeonnam_selected.jsonl')
    snapshot['legacy_jeonnam_pending_count'] = len(read_jsonl(snapshot['legacy_jeonnam_pending_path']))
    (stage / 'manifest.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
    normalized = stage / 'normalized.jsonl'
    for row in source_rows:
        row['data_version'] = snapshot['data_version']
        row['source_snapshot_file'] = str(STAGING / 'merged_policies_raw.jsonl')
    write_jsonl(normalized, normalize_policies.normalize_rows(source_rows))
    candidates = stage / 'region_candidates.csv'
    region_candidates.run(normalized, candidates)
    selected = region_selection.run(normalized, candidates, stage / 'region')
    elderly = elderly_filter.run(Path(selected['run_dir']) / 'policies_selected.jsonl', stage / 'elderly')
    policies = Path(elderly['run_dir']) / 'policies_elderly_selected.jsonl'
    rag = stage / 'rag'
    documents = rag / 'documents'
    policy_docs = documents / 'policy_documents.jsonl'
    build_docs(policies, policy_docs)
    # PDFs are independent of this API refresh. Copy matching source and sections into this candidate.
    source_docs = root / 'data/rag/documents'
    for name in ('source_documents.jsonl', 'guideline_documents.jsonl'):
        shutil.copyfile(source_docs / name, documents / name)
    chunk_report = build_chunks(policy_docs, documents / 'guideline_documents.jsonl', rag / 'chunks')
    # The old PDF chunks are not reused: both strategies are regenerated with the same parameters.
    _, checked = load_and_validate(root, policies, rag)
    report = {
        'snapshot': snapshot,
        'region': selected,
        'elderly': elderly,
        'documents': len(read_jsonl(policy_docs)),
        'chunk_totals': {k: v['total_chunks'] for k, v in chunk_report['strategies'].items()},
        'loader_check': {'counts': checked['counts'], 'warnings': checked['warnings']},
        'status': 'review_candidate_only_no_database_or_index_changes',
    }
    (stage / 'candidate_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve(), args.output_dir.resolve()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
