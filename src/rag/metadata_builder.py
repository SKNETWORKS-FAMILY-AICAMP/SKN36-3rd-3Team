"""STEP 5: local welfare policy metadata (Qdrant common schema, pre-chunk).

Input schema: STEP4 `policies_elderly_selected.jsonl`.
This file does NOT assign UUIDs, chunk IDs, or verify applicant eligibility.
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from typing import Any


def clean_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value if value and value.lower() not in {"nan", "none", "null", "<na>"} else None
    return str(value).strip() or None


def first_present(policy: dict, *keys: str) -> Any:
    for key in keys:
        v = policy.get(key)
        if v is None or (isinstance(v, str) and not clean_string(v)):
            continue
        return v
    return None


def as_list(value: Any) -> list[str]:
    """Normalize STEP2 tag lists (including JSON array strings) without guessing."""
    if value is None:
        return []
    if isinstance(value, str):
        raw = clean_string(value)
        if raw is None:
            return []
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return as_list(parsed)
        value = [x.strip() for x in raw.split(",")]
    elif not isinstance(value, (list, tuple, set)):
        value = [value]
    out: list[str] = []
    for item in value:
        s = clean_string(item)
        if s and s not in out:
            out.append(s)
    return out


def iso_date(value: Any) -> str | None:
    """Only ISO YYYY-MM-DD; invalid or absent dates -> None."""
    s = clean_string(value)
    if not s:
        return None
    digits = s.replace("-", "")
    if not re.fullmatch(r"\d{8}", digits):
        return None
    try:
        return datetime.strptime(digits, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def normalize_scope(value: Any) -> str:
    s = clean_string(value)
    return s if s in {"national", "sido", "sigungu", "unknown"} else "unknown"


def normalize_status(value: Any) -> str:
    # Local STEP2 values: pending / provisional. Keep values rather than implying verified.
    s = clean_string(value)
    return s if s else "unknown"


def make_policy_id(policy: dict) -> tuple[str, str]:
    raw = clean_string(policy.get("policy_id"))
    if not raw:
        raise ValueError("policy_id is missing")
    if raw.startswith("central:"):
        raise ValueError("Central policy supplied to local policy builder")
    serv_id = raw[6:] if raw.startswith("local:") else raw
    if not serv_id:
        raise ValueError("policy_id has empty local service ID")
    return f"local:{serv_id}", serv_id


def build_metadata(policy: dict) -> dict[str, Any]:
    """Canonical field names agreed with Qdrant teammate.

    Region-scope / region-review status remain *provisional* when unverified.
    For central policies, use a separate adapter with semantic value mappings.
    """
    _, serv_id = make_policy_id(policy)
    category = clean_string(first_present(policy, "elderly_category", "elderly_candidate_category"))
    if category not in {"direct", "indirect"}:
        raise ValueError(f"STEP5 accepts only selected direct/indirect records (got {category!r})")

    source_url = clean_string(policy.get("source_url"))
    if source_url and not re.match(r"^https?://", source_url, re.I):
        source_url = None

    raw_sido = clean_string(policy.get("raw_sido_name"))
    raw_sigungu = clean_string(policy.get("raw_sigungu_name"))
    sido = clean_string(policy.get("sido_name"))
    sigungu = clean_string(policy.get("sigungu_name"))
    region_label = clean_string(policy.get("region_selection_label"))
    # The API queried the combined '전남광주통합특별시' area. Only confirmed
    # inclusion labels are recorded as selection hints; do not misrepresent
    # the administrative geography or policy eligibility scope.
    if region_label == "jeonnam" and sido == "전남광주통합특별시":
        # For known former Jeonnam administrative areas, map display name.
        # Other cases keep the API area name, plus region selection label.
        if clean_string(policy.get("legacy_area_group")) == "former_jeonnam":
            sido = "전라남도"

    return {
        "record_type": "policy",
        "serv_id": serv_id,
        "title": clean_string(policy.get("title")),
        "source_type": "local_welfare_api",
        "source_url": source_url,
        "sido_name": sido,
        "sigungu_name": sigungu,
        "region_scope": normalize_scope(policy.get("region_scope")),
        "region_code": clean_string(policy.get("region_code")),
        "region_review_status": normalize_status(policy.get("region_review_status")),
        "region_selection_label": region_label,
        "region_selection_verified": policy.get("region_selection_verified") is True,
        "elderly_category": category,
        "themes": as_list(first_present(policy, "themes", "interest_tags", "themes_raw")),
        "target_groups": as_list(first_present(policy, "target_groups", "target_group_tags")),
        "life_stages": as_list(first_present(policy, "life_stages", "life_stage_tags")),
        "start_date": iso_date(policy.get("start_date")),
        "end_date": iso_date(policy.get("end_date")),
        "updated_at_source": iso_date(policy.get("updated_at_source")),
        "raw_sido_name": raw_sido,
        "raw_sigungu_name": raw_sigungu,
        "requested_region": clean_string(policy.get("requested_region")),
        "detail_fetched": policy.get("detail_fetched") is True,
        "department": clean_string(policy.get("department")),
        "contact": clean_string(policy.get("contact")),
        "application_method_name": clean_string(policy.get("application_method_name")),
        "policy_source_coverage": "api_only",  # PDF matching is not implemented in STEP 5.
    }
