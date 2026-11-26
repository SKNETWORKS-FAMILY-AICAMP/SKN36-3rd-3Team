"""A/B A: fixed-character-window chunking with overlap."""
from __future__ import annotations
import re
from .common import make_chunk


def split_fixed(text: str, chunk_size: int = 800, overlap: int = 150, *, preserve_contact_lines: bool = False) -> list[str]:
    if chunk_size < 1 or not 0 <= overlap < chunk_size:
        raise ValueError('chunk_size must be > overlap >= 0')
    if not text.strip():
        return []
    contact_lines = tuple(re.finditer(r"^문의처:[^\r\n]*", text, re.MULTILINE)) if preserve_contact_lines else ()
    if any(line.end() - line.start() > chunk_size for line in contact_lines):
        raise ValueError('contact line exceeds the chunk limit')
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        for line in contact_lines:
            if line.start() < end < line.end():
                end = line.start()
                break
        piece = text[start:end]
        if piece.strip():
            parts.append(piece)
        if end == len(text):
            break
        next_start = end - overlap
        for line in contact_lines:
            if line.start() < next_start < line.end():
                next_start = line.start() if line.start() > start else line.end()
                break
        if next_start <= start:
            next_start = end
        start = next_start
    return parts


def chunk_fixed(doc: dict, chunk_size: int = 800, overlap: int = 150) -> list[dict]:
    return [make_chunk(doc, 'fixed', i, text) for i, text in
            enumerate(split_fixed(doc['text'], chunk_size, overlap,
                                  preserve_contact_lines=doc.get('metadata', {}).get('record_type') == 'policy'), 1)]
