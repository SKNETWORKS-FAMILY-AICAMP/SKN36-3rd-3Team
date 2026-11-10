"""STEP 5 validation: check schema before atomic JSONL export."""
from __future__ import annotations
import re
from typing import Any

EXPECTED_TAG_LISTS = ("themes", "target_groups", "life_stages")
REQUIRED_METADATA_KEYS = (
    "record_type", "title", "source_url", "sido_name", "sigungu_name",
    "region_scope", "region_code", "region_review_status", "elderly_category",
    "themes", "target_groups", "life_stages", "start_date", "end_date",
    "raw_sido_name", "raw_sigungu_name", "region_selection_verified",
)


def validate_documents(documents: list[dict[str, Any]], *, strict: bool = True) -> dict[str, Any]:
    problems: list[dict[str, Any]] = []
    seen: set[str] = set()
    counts: dict[str, int] = {"direct": 0, "indirect": 0}
    unverified_regions = 0
    for i, doc in enumerate(documents):
        pid = doc.get("policy_id")
        meta = doc.get("metadata")
        errors: list[str] = []
        if not isinstance(pid, str) or not pid.startswith("local:") or len(pid) <= 6:
            errors.append("invalid policy_id")
        elif pid in seen:
            errors.append("duplicate policy_id")
        else:
            seen.add(pid)
        text = doc.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append("empty document text")
        if not isinstance(meta, dict):
            errors.append("invalid metadata")
        else:
            for k in REQUIRED_METADATA_KEYS:
                if k not in meta:
                    errors.append(f"missing metadata field: {k}")
            if not meta.get("title"):
                errors.append("empty title")
            if meta.get("record_type") != "policy":
                errors.append("invalid record_type")
            cat = meta.get("elderly_category")
            if cat not in counts:
                errors.append(f"unexpected elderly_category: {cat}")
            else:
                counts[cat] += 1
            for k in EXPECTED_TAG_LISTS:
                if not isinstance(meta.get(k), list):
                    errors.append(f"{k} must be a list")
            for k in ("start_date", "end_date"):
                d = meta.get(k)
                if d is not None and (not isinstance(d, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)):
                    errors.append(f"invalid {k} format")
            if not meta.get("region_selection_verified"):
                unverified_regions += 1
        if errors:
            problems.append({"row": i + 1, "policy_id": pid, "errors": errors})
    summary = {
        "documents": len(documents),
        "direct": counts["direct"],
        "indirect": counts["indirect"],
        "unverified_region_selection": unverified_regions,
        "errors": len(problems),
        "error_samples": problems[:15],
    }
    if strict and problems:
        raise ValueError(f"Document validation failed: {summary['error_samples']}")
    return summary
