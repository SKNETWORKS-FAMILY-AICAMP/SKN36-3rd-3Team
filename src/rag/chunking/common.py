"""Shared deterministic chunk schema for STEP 7."""
from __future__ import annotations
import uuid
from typing import Any


def parent_id(doc: dict[str, Any]) -> tuple[str, str]:
    meta = doc.get('metadata')
    if not isinstance(meta, dict):
        raise ValueError('metadata must be an object')
    record_type = meta.get('record_type')
    if record_type == 'policy':
        key = doc.get('policy_id')
    elif record_type == 'guideline':
        key = doc.get('section_id')
    else:
        raise ValueError(f'unsupported record_type: {record_type!r}')
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f'missing parent id for {record_type}')
    return record_type, key


def make_chunk(doc: dict[str, Any], strategy: str, number: int, content: str) -> dict[str, Any]:
    kind, key = parent_id(doc)
    if not content or not content.strip():
        raise ValueError('empty chunk')
    chunk_id = f'{kind}::{key}::{strategy}::{number:04d}'
    # Qdrant-compatible deterministic point ID; different strategies never collide.
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
    metadata = dict(doc['metadata'])
    metadata['chunk_id'] = chunk_id
    metadata['chunk_strategy'] = strategy
    metadata['parent_id'] = key
    result = {
        'id': point_id,
        'chunk_id': chunk_id,
        'text': content,
        'metadata': metadata,
    }
    if kind == 'policy':
        result['policy_id'] = key
    else:
        result['section_id'] = key
    return result


def validate_chunks(chunks: list[dict[str, Any]], docs: list[dict[str, Any]], strategy: str) -> dict[str, Any]:
    errors = []
    ids, cids = set(), set()
    parents = set()
    for i, chunk in enumerate(chunks):
        cid, point_id = chunk.get('chunk_id'), chunk.get('id')
        if cid in cids or point_id in ids:
            errors.append(f'duplicate id at chunk {i}')
        cids.add(cid)
        ids.add(point_id)
        if not isinstance(cid, str) or str(uuid.uuid5(uuid.NAMESPACE_URL, cid)) != point_id:
            errors.append(f'bad UUID at chunk {i}')
        meta = chunk.get('metadata', {})
        if meta.get('chunk_id') != cid or meta.get('chunk_strategy') != strategy:
            errors.append(f'bad chunk metadata at chunk {i}')
        if not chunk.get('text', '').strip():
            errors.append(f'empty chunk {i}')
        parents.add((meta.get('record_type'), meta.get('parent_id')))
    expected = set(parent_id(doc) for doc in docs)
    missing = expected - parents
    if missing:
        errors.append(f'{len(missing)} input documents have no chunks')
    return {'strategy': strategy, 'input_documents': len(docs), 'chunks': len(chunks),
            'unique_parent_documents': len(parents), 'errors': errors,
            'min_chunk_chars': min((len(c['text']) for c in chunks), default=0),
            'avg_chunk_chars': round(sum(len(c['text']) for c in chunks)/len(chunks), 2) if chunks else 0,
            'max_chunk_chars': max((len(c['text']) for c in chunks), default=0)}
