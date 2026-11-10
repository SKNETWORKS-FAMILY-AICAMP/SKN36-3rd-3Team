"""Convert one normalized guideline section to one *un-chunked* RAG document."""
from __future__ import annotations

from typing import Any

from .guideline_metadata_builder import build_metadata


def build_guideline_document(section: dict[str, Any]) -> dict[str, Any]:
    metadata = build_metadata(section)
    headings = [section.get("title"), section.get("section")]
    headings.extend(section.get("subsection") or [])
    unique = []
    for x in headings:
        if x and x not in unique:
            unique.append(x)
    heading = " > ".join(unique)
    text = (f"목차: {heading}\n\n" if heading else "") + section["content"]
    return {"section_id": section["section_id"], "text": text, "metadata": metadata}


def build_guideline_documents(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_guideline_document(s) for s in sections]
