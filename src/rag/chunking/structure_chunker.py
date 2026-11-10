"""A/B B: document-structure-aware chunking; preserve labeled policy fields.

PDF blocks use paragraph / line / punctuation boundaries, with deterministic
fixed-window fallback for long uninterrupted spans. The original text remains
unchanged in the chunk content (only boundary whitespace may be trimmed).
"""
from __future__ import annotations
import re
from .common import make_chunk
from .fixed_chunker import split_fixed

_POLICY_LABEL = re.compile(r'(?m)^(?=(?:사업명|지역|사업 개요|지원 대상|선정 기준|지원 내용|신청 방법|신청 방식|담당 부서|문의처):)')


def _split_long(block: str, limit: int, overlap: int) -> list[str]:
    """Split long blocks on newlines/sentences where possible; ensure progress."""
    if len(block) <= limit:
        return [block] if block.strip() else []
    parts = []
    start = 0
    while start < len(block):
        stop = min(start + limit, len(block))
        if stop < len(block):
            window = block[start:stop]
            # Avoid splitting inside a sentence/table row where feasible.
            candidates = [window.rfind('\n'), window.rfind('. '), window.rfind('다. '), window.rfind('요. ')]
            choice = max(candidates)
            if choice >= int(limit * .45):
                stop = start + choice + (1 if window[choice:choice+1] == '\n' else 2)
        piece = block[start:stop].strip()
        if piece:
            parts.append(piece)
        if stop >= len(block):
            break
        next_start = max(start + 1, stop - overlap)
        start = next_start
    return parts


def _policy_units(text: str) -> list[str]:
    # Each labeled field is a semantic boundary; preserve multiline values.
    blocks = [x.strip() for x in _POLICY_LABEL.split(text) if x.strip()]
    return blocks if blocks else [text]


def _guideline_units(text: str) -> list[str]:
    # First prefer paragraphs. If a PDF section has no blank lines, keep its
    # lines as units so numeric criteria and table rows are not merged blindly.
    paragraphs = [x.strip() for x in re.split(r'\n\s*\n', text) if x.strip()]
    if len(paragraphs) <= 1:
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        return lines if len(lines) > 1 else paragraphs
    return paragraphs


def split_structure(text: str, record_type: str, chunk_size: int = 800,
                    overlap: int = 150) -> list[str]:
    if chunk_size < 1 or not 0 <= overlap < chunk_size:
        raise ValueError('chunk_size must be > overlap >= 0')
    if not text.strip():
        return []
    units = _policy_units(text) if record_type == 'policy' else _guideline_units(text)
    out: list[str] = []
    acc = ''
    for unit in units:
        if len(unit) > chunk_size:
            if acc:
                out.append(acc)
                acc = ''
            out.extend(_split_long(unit, chunk_size, overlap))
            continue
        if not acc:
            acc = unit
        elif len(acc) + 1 + len(unit) <= chunk_size:
            acc += '\n' + unit
        else:
            out.append(acc)
            acc = unit
    if acc:
        out.append(acc)
    # Avoid orphan snippets (a heading or a 1-character tail) when the parent
    # document has enough context for two reasonably sized chunks.
    min_chars = min(80, max(1, chunk_size // 5))
    i = 0
    while i < len(out):
        if len(out[i]) >= min_chars or len(out) == 1:
            i += 1
            continue
        if i > 0 and len(out[i - 1]) + 1 + len(out[i]) <= chunk_size:
            out[i - 1] += "\n" + out.pop(i)
            i = max(0, i - 1)
        elif i + 1 < len(out) and len(out[i]) + 1 + len(out[i + 1]) <= chunk_size:
            out[i + 1] = out.pop(i) + "\n" + out[i]
        else:
            neighbor = i - 1 if i > 0 else i + 1
            pair = out[neighbor] + "\n" + out[i] if neighbor < i else out[i] + "\n" + out[neighbor]
            cut = len(pair) // 2
            # Prefer nearby newline; otherwise split in the middle.
            nl = pair.rfind("\n", max(1, cut - 80), min(len(pair), cut + 80))
            if nl > 0 and len(pair) - (nl + 1) <= chunk_size:
                cut = nl + 1
            left, right = pair[:cut].strip(), pair[cut:].strip()
            if neighbor < i:
                out[neighbor], out[i] = left, right
            else:
                out[i], out[neighbor] = left, right
            i += 1
    return [x for x in out if x.strip()]


def chunk_structure(doc: dict, chunk_size: int = 800, overlap: int = 150) -> list[dict]:
    record_type = doc['metadata']['record_type']
    return [make_chunk(doc, 'structure', i, text) for i, text in
            enumerate(split_structure(doc['text'], record_type, chunk_size, overlap), 1)]
