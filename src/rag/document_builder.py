"""STEP 5: build one unchunked RAG document per policy.

The original wording is kept. No inference on amounts, eligibility or region.
"""
from __future__ import annotations
from typing import Any
from .metadata_builder import build_metadata, clean_string, make_policy_id

# Purposefully build a coherent, labeled text instead of arbitrary character chunks.
TEXT_FIELDS = (
    ("사업명", "title"),
    ("지역", None),
    ("사업 개요", "summary"),
    ("지원 대상", "target_text"),
    ("선정 기준", "selection_criteria_text"),
    ("지원 내용", "benefit_text"),
    ("신청 방법", "application_text"),
    ("신청 방식", "application_method_name"),
    ("담당 부서", "department"),
    ("문의처", "contact"),
)


def build_policy_document(policy: dict[str, Any]) -> dict[str, Any]:
    policy_id, _ = make_policy_id(policy)
    metadata = build_metadata(policy)
    fragments: list[str] = []
    for label, key in TEXT_FIELDS:
        if key is None:
            region = " ".join(
                v for v in (metadata["sido_name"], metadata["sigungu_name"]) if v
            )
            if region:
                fragments.append(f"{label}: {region}")
        else:
            value = clean_string(policy.get(key))
            if value:
                fragments.append(f"{label}: {value}")
    return {
        "policy_id": policy_id,
        "text": "\n".join(fragments),
        "metadata": metadata,
    }


def build_policy_documents(policies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_policy_document(p) for p in policies]
