"""Build PDF guideline metadata using an explicit source registry.

Page numbers from the supplied JSONL refer to *PDF file pages*, not printed pages.
Unknown official source URLs are deliberately null.
"""
from __future__ import annotations

from typing import Any

DOCUMENTS = {
    "2026_기초연금_사업안내": ("mohw_basic_pension_2026", "2026년 기초연금 사업안내"),
    "2026_나에게_힘이_되는_복지서비스": ("mohw_welfare_services_2026", "2026 나에게 힘이 되는 복지서비스"),
    "2026_노인보건복지사업안내_1권": ("mohw_elderly_welfare_vol1_2026", "2026년 노인보건복지사업안내 1권"),
    "2026_노인보건복지사업안내_2권": ("mohw_elderly_welfare_vol2_2026", "2026년 노인보건복지사업안내 2권"),
}


def build_metadata(section: dict[str, Any]) -> dict[str, Any]:
    source = section["source"]
    if source not in DOCUMENTS:
        raise ValueError(f"Unknown source: {source!r}. Add it to DOCUMENTS only after verification.")
    document_id, document_title = DOCUMENTS[source]
    return {
        "record_type": "guideline",
        "document_id": document_id,
        "source": source,
        "title": document_title,
        "chapter": section["title"],
        "section": section["section"],
        "subsection": section["subsection"],
        "section_id": section["section_id"],
        "page_start": section["page_start"],
        "page_end": section["page_end"],
        "images": section["images"],
        "source_type": "official_pdf_guideline",
        "source_url": None,
        "publisher": "보건복지부",
        "publication_year": 2026,
        "region_scope": "national",
        "sido_name": None,
        "sigungu_name": None,
        "themes": [],
        "target_groups": [],
        "life_stages": [],
    }


def source_document_records() -> list[dict[str, Any]]:
    return [
        {"document_id": doc_id, "title": title, "source": source,
         "publisher": "보건복지부", "publication_year": 2026,
         "document_type": "official_guideline", "source_url": None}
        for source, (doc_id, title) in DOCUMENTS.items()
    ]
