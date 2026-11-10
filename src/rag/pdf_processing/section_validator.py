"""Validate and normalize the existing guideline_sections_filtered.jsonl (no PDF extraction).

The input's nested arrays may have been serialized to Python-repr strings.
We parse them safely with json.loads and ast.literal_eval; never use eval.
"""
from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any

REQUIRED = ("section_id", "source", "content", "page_start", "page_end")


def clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return None if s.lower() in ("", "none", "null", "nan", "<na>") else s


def parse_list(value: Any, field: str) -> list[Any]:
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "none", "null")):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(value)
                if isinstance(parsed, list):
                    return parsed
            except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
                pass
    raise ValueError(f"{field}: expected list or serialized list; got {str(value)[:80]!r}")


def parse_page(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: boolean is not a page number")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: invalid page number {value!r}") from exc
    if result < 1 or str(value).strip() != str(result):
        raise ValueError(f"{field}: expected positive integer, got {value!r}")
    return result


def normalize_section(raw: dict[str, Any]) -> dict[str, Any]:
    for field in REQUIRED:
        if clean_optional(raw.get(field)) is None:
            raise ValueError(f"missing required field: {field}")
    start = parse_page(raw["page_start"], "page_start")
    end = parse_page(raw["page_end"], "page_end")
    if end < start:
        raise ValueError(f"page_end {end} < page_start {start}")
    subsection_value = raw.get("subsection")
    # Aggregated JSONL uses scalar headings (including headings that begin
    # with "[서식 ...]") as well as list-encoded headings.
    if isinstance(subsection_value, str) and clean_optional(subsection_value):
        try:
            subsection_items = parse_list(subsection_value, "subsection")
        except ValueError:
            subsection_items = [subsection_value]
    else:
        subsection_items = parse_list(subsection_value, "subsection")
    subs = [s for item in subsection_items if (s := clean_optional(item))]
    imgs = []
    for i, item in enumerate(parse_list(raw.get("images"), "images")):
        if not isinstance(item, dict):
            raise ValueError(f"images[{i}]: expected object")
        path = clean_optional(item.get("path"))
        if not path:
            raise ValueError(f"images[{i}]: missing path")
        imgs.append({"path": path, "description": clean_optional(item.get("description"))})
    return {
        "section_id": str(raw["section_id"]).strip(),
        "source": str(raw["source"]).strip(),
        "title": clean_optional(raw.get("title")),
        "section": clean_optional(raw.get("section")),
        "subsection": subs,
        "content": str(raw["content"]).strip(),
        "page_start": start,
        "page_end": end,
        "images": imgs,
    }


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as stream:
        for lineno, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ValueError("JSONL row must be object")
                yield lineno, obj
            except (json.JSONDecodeError, ValueError) as exc:
                yield lineno, {"__error__": str(exc)}


def validate_sections(input_path: Path, image_root: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records, errors, warnings = [], [], []
    seen = set()
    source_counts: Counter[str] = Counter()
    missing_images = set()
    for lineno, raw in read_jsonl(input_path):
        if "__error__" in raw:
            errors.append({"line": lineno, "error": raw["__error__"]})
            continue
        try:
            doc = normalize_section(raw)
            if doc["section_id"] in seen:
                raise ValueError(f"duplicate section_id: {doc['section_id']}")
            seen.add(doc["section_id"])
            source_counts[doc["source"]] += 1
            if doc["title"] is None or doc["section"] is None:
                warnings.append({"section_id": doc["section_id"], "warning": "missing title or section heading"})
            if len(doc["content"]) > 12000:
                warnings.append({"section_id": doc["section_id"], "warning": "long section; needs chunking"})
            if image_root is not None:
                for img in doc["images"]:
                    target = (image_root / img["path"]).resolve()
                    root = image_root.resolve()
                    if not target.is_relative_to(root) or not target.is_file():
                        missing_images.add(img["path"])
            records.append(doc)
        except ValueError as exc:
            errors.append({"line": lineno, "section_id": raw.get("section_id"), "error": str(exc)})
    report = {
        "input": str(input_path), "total_rows": len(records) + len(errors),
        "valid_sections": len(records), "errors_count": len(errors), "errors": errors[:100],
        "warnings_count": len(warnings), "warnings": warnings[:200],
        "sources": dict(sorted(source_counts.items())),
        "missing_image_paths_count": len(missing_images),
        "missing_image_paths": sorted(missing_images)[:100],
        "image_files_checked": image_root is not None,
        "max_content_characters": max((len(r["content"]) for r in records), default=0),
    }
    return records, report


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for obj in records:
            stream.write(json.dumps(obj, ensure_ascii=False) + "\n")
