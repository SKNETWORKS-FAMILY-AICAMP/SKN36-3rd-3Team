"""A/B A: fixed-character-window chunking with overlap."""
from __future__ import annotations
from .common import make_chunk


def split_fixed(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    if chunk_size < 1 or not 0 <= overlap < chunk_size:
        raise ValueError('chunk_size must be > overlap >= 0')
    if not text.strip():
        return []
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        piece = text[start:end]
        if piece.strip():
            parts.append(piece)
        if end == len(text):
            break
        start = end - overlap
    return parts


def chunk_fixed(doc: dict, chunk_size: int = 800, overlap: int = 150) -> list[dict]:
    return [make_chunk(doc, 'fixed', i, text) for i, text in
            enumerate(split_fixed(doc['text'], chunk_size, overlap), 1)]
