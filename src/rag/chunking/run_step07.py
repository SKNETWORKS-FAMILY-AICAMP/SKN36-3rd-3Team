"""Generate two independently reproducible chunking variants from STEP 5+6 JSONL."""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from .common import parent_id, validate_chunks
from .fixed_chunker import chunk_fixed
from .structure_chunker import chunk_structure


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f'Input not found: {path}. Specify --policy / --guideline')
    results = []
    with path.open(encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            if line.strip():
                try:
                    obj = json.loads(line)
                    parent_id(obj)
                    if not isinstance(obj.get('text'), str) or not obj['text'].strip():
                        raise ValueError('text must be a nonempty string')
                    results.append(obj)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f'{path}:{lineno}: {exc}') from exc
    ids = [parent_id(x) for x in results]
    if len(ids) != len(set(ids)):
        raise ValueError(f'duplicate source IDs in {path}')
    return results


def write_jsonl(path: Path, chunks: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        for item in chunks:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')


def build(policy_path: Path, guideline_path: Path, output_dir: Path,
          chunk_size: int = 800, overlap: int = 150) -> dict:
    if chunk_size < 1 or not 0 <= overlap < chunk_size:
        raise ValueError('chunk_size must be > overlap >= 0')
    policy_docs = read_jsonl(policy_path)
    guideline_docs = read_jsonl(guideline_path)
    if any(x['metadata']['record_type'] != 'policy' for x in policy_docs):
        raise ValueError('policy file contains non-policy documents')
    if any(x['metadata']['record_type'] != 'guideline' for x in guideline_docs):
        raise ValueError('guideline file contains non-guideline documents')
    report = {'settings': {'chunk_size_chars': chunk_size, 'overlap_chars': overlap,
                           'id_rule': 'uuid.uuid5(uuid.NAMESPACE_URL, chunk_id)',
                           'evaluation': 'retrieval A/B not yet performed; embedding and query labels required'},
              'inputs': {'policies': len(policy_docs), 'guidelines': len(guideline_docs)},
              'strategies': {}}
    for strategy, chunker in [('A_fixed', chunk_fixed), ('B_structure', chunk_structure)]:
        params = {'chunk_size': chunk_size, 'overlap': overlap}
        policy_chunks = [c for doc in policy_docs for c in chunker(doc, **params)]
        guideline_chunks = [c for doc in guideline_docs for c in chunker(doc, **params)]
        strategy_label = 'fixed' if strategy == 'A_fixed' else 'structure'
        report['strategies'][strategy] = {}
        for name, docs, chunks in [('policy',policy_docs,policy_chunks),('guideline',guideline_docs,guideline_chunks)]:
            stats = validate_chunks(chunks, docs, strategy_label)
            report['strategies'][strategy][name] = stats
            if stats['errors']:
                raise ValueError(f'{strategy}/{name}: {stats["errors"][:5]}')
            write_jsonl(output_dir / strategy / f'{name}_chunks.jsonl', chunks)
        report['strategies'][strategy]['total_chunks'] = len(policy_chunks)+len(guideline_chunks)
    report_path = output_dir / 'step07_chunking_report.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description='STEP 7: A/B policy and guideline chunking')
    parser.add_argument('--policy', default='data/rag/documents/policy_documents.jsonl', type=Path)
    parser.add_argument('--guideline', default='data/rag/documents/guideline_documents.jsonl', type=Path)
    parser.add_argument('--output', default='data/rag/chunks', type=Path)
    parser.add_argument('--chunk-size', default=800, type=int)
    parser.add_argument('--overlap', default=150, type=int)
    args = parser.parse_args()
    report = build(args.policy, args.guideline, args.output, args.chunk_size, args.overlap)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
