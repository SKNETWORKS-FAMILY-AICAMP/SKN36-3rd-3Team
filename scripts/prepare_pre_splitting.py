"""SKN36 RAG: source preservation -> normalization -> semantic-document staging.

This script STOPS BEFORE RAG CHUNKING. It never calls an API, embeds, or indexes.
Only /data/staging, /data/processed, and /data/validation are written.
Run from repository root:
    uv run python scripts/prepare_pre_splitting.py --root .
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
DATE_SENTINELS = {"00000000", "99991231", "9999-12-31", "", "null", "None"}
VALID_REGIONS = {"서울특별시", "경기도", "전북특별자치도", "전라남도"}
REGION_ALIASES = {"서울": "서울특별시", "서울시": "서울특별시", "경기": "경기도", "전북": "전북특별자치도", "전라북도": "전북특별자치도", "전남": "전라남도"}


def clean(value: Any) -> str | None:
    if value is None:
        return None
    value = unicodedata.normalize("NFC", str(value)).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ").strip()
    return value if value and value.lower() not in {"nan", "none", "null"} else None


def first(*values: Any) -> str | None:
    return next((v for value in values if (v := clean(value)) is not None), None)


def normalize_date(value: Any) -> tuple[str | None, str]:
    raw = clean(value)
    if raw is None:
        return None, "missing"
    if raw in DATE_SENTINELS:
        return None, "open_or_placeholder" if raw.startswith("9999") else "placeholder"
    s = raw.replace("-", "").replace("/", "").replace(".", "")
    if not re.fullmatch(r"\d{8}", s):
        return None, "invalid"
    try:
        d = date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
        return d.isoformat(), "parsed"
    except ValueError:
        return None, "invalid"


def url_format_ok(value: Any) -> bool:
    raw = clean(value)
    if not raw:
        return False
    parts = urlparse(raw)
    return parts.scheme in {"http", "https"} and bool(parts.hostname) and not parts.username and not parts.password


def region(value: Any) -> str | None:
    s = clean(value)
    if s is None or s == "-":
        return None
    return REGION_ALIASES.get(s, s)


def possible_county(value: Any) -> str | None:
    s = clean(value)
    return s if s not in {None, "-"} else None


def stable_id(prefix: str, original: Any) -> str:
    raw = clean(original)
    if not raw or not re.fullmatch(r"[\w.-]+", raw):
        raise ValueError("Missing or invalid original service identifier")
    return f"{prefix}:{raw}"


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
    tmp.replace(path)


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def parse_repeat(child: ET.Element) -> dict[str, Any]:
    if not list(child):
        return {"value": clean(child.text)}
    obj: dict[str, Any] = {}
    for sub in child:
        value = clean(sub.text) if not list(sub) else parse_repeat(sub)
        if sub.tag not in obj:
            obj[sub.tag] = value
        elif isinstance(obj[sub.tag], list):
            obj[sub.tag].append(value)
        else:
            obj[sub.tag] = [obj[sub.tag], value]
    return obj


def parse_central_xml(path: Path) -> dict[str, Any]:
    root = ET.fromstring(path.read_bytes())
    if root.tag != "wantedDtl":
        raise ValueError("Unexpected XML root")
    if first(root.findtext("resultCode")) != "0":
        raise ValueError("API resultCode not successful")
    if clean(root.findtext("servId")) != path.stem:
        raise ValueError("XML servId does not match filename")
    if not clean(root.findtext("servNm")):
        raise ValueError("Missing XML service name")
    result: dict[str, Any] = {}
    for ch in root:
        if ch.tag in {"resultCode", "resultMessage"}:
            continue
        value = clean(ch.text) if not list(ch) else parse_repeat(ch)
        if ch.tag not in result:
            result[ch.tag] = value
        elif isinstance(result[ch.tag], list):
            result[ch.tag].append(value)
        else:
            result[ch.tag] = [result[ch.tag], value]
    return result


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as fh:
        for i, line in enumerate(fh, 1):
            if line.strip():
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        raise ValueError("Not an object")
                    yield obj
                except Exception as e:
                    raise ValueError(f"Invalid JSONL line {i} in {path.name}: {type(e).__name__}") from None


def central_policy(item: dict[str, Any], detail: dict[str, Any] | None, list_path: Path, detail_path: Path | None) -> dict[str, Any]:
    serv_id = clean(item.get("servId"))
    if not serv_id:
        raise ValueError("Central list entry missing servId")
    d = detail or {}
    start, start_status = normalize_date(None)
    end, end_status = normalize_date(None)
    steps = d.get("applmetList") or []
    if isinstance(steps, dict):
        steps = [steps]
    if not isinstance(steps, list):
        steps = []
    application = "\n".join(
        f"{i+1}. {first(st.get('servSeDetailNm'), '절차')}: {first(st.get('servSeDetailLink'), '')}"
        for i, st in enumerate(steps) if isinstance(st, dict)
    ) or None
    target = clean(d.get("tgtrDtlCn"))
    selection = clean(d.get("slctCritCn"))
    benefit = clean(d.get("alwServCn"))
    quality = "list_only" if not detail else ("detail_complete" if target and selection and benefit and application else "detail_partial")
    return {
        "policy_id": stable_id("central", serv_id),
        "source_type": "central_welfare_api", "source_serv_id": serv_id,
        "title": first(d.get("servNm"), item.get("servNm")),
        "summary": first(d.get("wlfareInfoOutlCn"), item.get("servDgst")),
        "sido_name": None, "sigungu_name": None, "region_scope": "unknown", "region_validation_status": "pending",
        "target_text": target, "selection_criteria_text": selection,
        "benefit_text": benefit, "application_text": application, "application_steps": steps,
        "department": first(d.get("jurMnofNm"), item.get("jurMnofNm")),
        "contact": first(d.get("rprsCtadr"), item.get("rprsCtadr")),
        "source_url": clean(item.get("servDtlLink")), "source_url_format_valid": url_format_ok(item.get("servDtlLink")),
        "publication_year": clean(d.get("crtrYr")), "updated_at_source": None, "updated_at_source_status": "missing", "raw_updated_at_source": None,
        "start_date": start, "end_date": end, "start_date_status": start_status, "end_date_status": end_status,
        "raw_start_date": None, "raw_end_date": None,
        "life_stages_raw": first(d.get("lifeArray"), item.get("lifeArray")),
        "target_groups_raw": first(d.get("trgterIndvdlArray"), item.get("trgterIndvdlArray")),
        "themes_raw": first(d.get("intrsThemaArray"), item.get("intrsThemaArray")),
        "benefit_frequency_raw": first(d.get("sprtCycNm"), item.get("sprtCycNm")),
        "source_coverage": "api_only", "detail_fetched": detail is not None, "quality_status": quality,
        "legal_references": d.get("baslawList") or [], "required_forms": d.get("basfrmList") or [],
        "additional_contacts": d.get("inqplCtadrList") or [], "additional_sites": d.get("inqplHmpgReldList") or [],
        "source_file_list": list_path.as_posix(),
        "source_file_detail": detail_path.as_posix() if detail and detail_path else None,
        "extraction_status": "not_applicable",
        "policy_relation_review_status": "unlinked",
    }


def local_policy(item: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    serv_id = clean(item.get("servId"))
    if not serv_id:
        raise ValueError("Local list entry missing servId")
    detail_state = str(item.get("detail_fetched", "")).strip().lower() in {"true", "1", "yes"}
    st, st_status = normalize_date(item.get("detail_enfcBgngYmd"))
    en, en_status = normalize_date(item.get("detail_enfcEndYmd"))
    raw_updated = first(item.get("detail_lastModYmd"), item.get("lastModYmd"))
    updated_at, updated_status = normalize_date(raw_updated)
    sido = region(first(item.get("detail_ctpvNm"), item.get("ctpvNm"), item.get("requested_region")))
    county = possible_county(first(item.get("detail_sggNm"), item.get("sggNm")))
    region_scope = "unknown"  # Government data scope requires explicit validation, not inference from missing county.
    raw_target = first(item.get("detail_sprtTrgtCn"))
    raw_criteria = first(item.get("detail_slctCritCn"))
    raw_benefit = first(item.get("detail_alwServCn"))
    quality = "list_only" if not detail_state else ("detail_complete" if raw_target and raw_criteria and raw_benefit and first(item.get("detail_aplyMtdCn")) else "detail_partial")
    return {
        "policy_id": stable_id("local", serv_id), "source_type": "local_welfare_api", "source_serv_id": serv_id,
        "title": first(item.get("detail_servNm"), item.get("servNm")),
        "summary": first(item.get("detail_servDgst"), item.get("servDgst")),
        "sido_name": sido, "sigungu_name": county, "region_scope": region_scope,
        "region_validation_status": "pending", "target_text": raw_target,
        "selection_criteria_text": raw_criteria, "benefit_text": raw_benefit,
        "application_text": first(item.get("detail_aplyMtdCn")), "application_steps": [],
        "application_channel_raw": first(item.get("detail_aplyMtdNm"), item.get("aplyMtdNm")),
        "department": first(item.get("detail_bizChrDeptNm"), item.get("bizChrDeptNm")),
        "contact": first(item.get("detail_inqNum"), item.get("inqNum")),
        "source_url": clean(item.get("servDtlLink")), "source_url_format_valid": url_format_ok(item.get("servDtlLink")),
        "publication_year": None, "updated_at_source": updated_at, "updated_at_source_status": updated_status, "raw_updated_at_source": raw_updated,
        "start_date": st, "end_date": en, "start_date_status": st_status, "end_date_status": en_status,
        "raw_start_date": clean(item.get("detail_enfcBgngYmd")), "raw_end_date": clean(item.get("detail_enfcEndYmd")),
        "life_stages_raw": first(item.get("detail_lifeNmArray"), item.get("lifeNmArray")),
        "target_groups_raw": first(item.get("detail_trgterIndvdlNmArray"), item.get("trgterIndvdlNmArray")),
        "themes_raw": first(item.get("detail_intrsThemaNmArray"), item.get("intrsThemaNmArray")),
        "benefit_frequency_raw": first(item.get("detail_sprtCycNm"), item.get("sprtCycNm")),
        "source_coverage": "api_only", "detail_fetched": detail_state, "quality_status": quality,
        "legal_references": [], "required_forms": [], "additional_contacts": [], "additional_sites": [],
        "source_file_list": raw_path.as_posix(), "source_file_detail": None,
        "extraction_status": "not_applicable", "policy_relation_review_status": "unlinked",
    }


def elderly_relevance(policy: dict[str, Any]) -> tuple[str, str]:
    """Candidate selection, not a decision about legal eligibility or policy exclusion."""
    life = clean(policy.get("life_stages_raw")) or ""
    if "노년" in life or "노인" in life or "고령" in life:
        return "candidate", "original_life_stage_tag"
    corpus = " ".join(clean(policy.get(k)) or "" for k in ("title", "summary", "target_text", "benefit_text"))
    if re.search(r"노인|노년|고령|65\s*세|기초연금|장기요양|치매|어르신|독거", corpus):
        return "candidate", "source_text_mention"
    return "unclassified_needs_review", "no_specific_older_adult_evidence"


def facility_row(f: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    id_ = clean(f.get("_feature_id"))
    if not id_:
        raise ValueError("Facility missing _feature_id")
    def coordinate(name: str, low: float, high: float):
        v = f.get(name)
        if v in ("", None):
            return None
        try:
            n = float(v)
            return n if low <= n <= high else None
        except (ValueError, TypeError):
            return None
    lat, lon = coordinate("latitude", -90, 90), coordinate("longitude", -180, 180)
    return {
        "facility_id": stable_id("vworld", id_), "source_id": id_,
        "name": clean(f.get("fac_nam")), "facility_type": clean(f.get("cat_nam")),
        "address_road": clean(f.get("fac_n_add")), "address_lot": clean(f.get("fac_o_add")),
        "phone": clean(f.get("fac_tel")), "latitude": lat, "longitude": lon,
        "sido_name": region(f.get("region")), "region_validation_status": "pending",
        "source_type": "vworld_elderly_facilities", "source_file": raw_path.as_posix(),
        "policy_operator_relation_verified": False,
    }


def find_local_data(root: Path) -> Path | None:
    base = root / "data" / "raw" / "api" / "local_welfare_service_outputs"
    # One merged dataset only: never concatenate both CSV and JSONL.
    for pattern in ("welfare_all_full_*.jsonl", "welfare_all_full_*.csv"):
        files = sorted(base.glob(pattern))
        if files:
            return files[-1]
    return None


def load_local(path: Path):
    if path.suffix == ".jsonl":
        yield from read_jsonl(path)
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            yield from csv.DictReader(fh)


def get_pdf_outlines(doc, page_count: int) -> list[dict[str, Any]]:
    try:
        toc = doc.get_toc(simple=True)  # PyMuPDF
        candidates = [{"level": x[0], "title": clean(x[1]), "start": int(x[2])} for x in toc if 1 <= int(x[2]) <= page_count]
        return candidates
    except Exception:
        return []


def extract_pdfs(root: Path, staging: Path, processed: Path, validation: Path) -> dict[str, Any]:
    pdfs = sorted((root / "data" / "raw" / "pdf").glob("*.pdf"))
    documents, pages, sections, tables, pdf_review = [], [], [], [], []
    try:
        import fitz
    except ImportError:
        fitz = None
    if pdfs and fitz is None:
        raise SystemExit("PDF files detected but PyMuPDF is unavailable. Run: uv add pymupdf")
    for fp in pdfs:
        digest = hashlib.sha256(fp.read_bytes()).hexdigest()
        document_id = "pdf:" + digest[:16]
        doc = fitz.open(fp)
        n = len(doc)
        headings = get_pdf_outlines(doc, n)
        documents.append({"document_id": document_id, "title": fp.stem, "publisher": "출처 확인 필요", "publication_year": 2026 if "2026" in fp.stem else None,
                          "document_type": "official_guideline_candidate", "source_file_hash": digest, "file_name": fp.name,
                          "source_file": fp.relative_to(root).as_posix(), "pages": n, "review_status": "pending",
                          "version_status": "current_as_collected_not_verified"})
        page_texts = []
        for i in range(n):
            page = doc.load_page(i)
            text = page.get_text("text", sort=True).replace("\x00", "").strip()
            page_texts.append(text)
            pages.append({"document_id": document_id, "page_number": i + 1, "text": text, "extraction_method": "pymupdf", "source_file": fp.name,
                          "text_extraction_status": "extracted_unreviewed" if text else "empty_needs_review"})
            if not text or re.search(r"\d{1,3}(?:,\d{3})+\s*원|선정기준액|소득인정액|기준\s*금액", text):
                pdf_review.append({"document_id": document_id, "file_name": fp.name, "page_number": i+1,
                                   "reason": "empty_page_or_financial_conditions; compare visually with original"})
            try:
                finder = page.find_tables()
                for k, table in enumerate(finder.tables):
                    t = table.extract()
                    if t:
                        tables.append({"document_id": document_id, "page_number": i+1, "table_index": k,
                                       "rows": t, "review_status": "pending", "extraction_method": "pymupdf_find_tables"})
            except Exception:
                pass
        if headings:
            # A section is a unique starting page from PDF bookmarks, not an arbitrary character chunk.
            by_page = defaultdict(list)
            for h in headings:
                by_page[h["start"]].append(h)
            starts = sorted(set([1] + list(by_page)))
            for seq, start in enumerate(starts):
                end = starts[seq+1] - 1 if seq + 1 < len(starts) else n
                title = by_page[start][-1]["title"] if by_page[start] else "표지·서문 또는 앞부분"
                sections.append({"section_id": f"{document_id}::section_{seq+1:04d}", "document_id": document_id,
                                 "section_title": title, "program_name": None, "page_start": start, "page_end": end,
                                 "text": "\n\n".join(page_texts[start-1:end]), "section_method": "pdf_bookmark_page_range",
                                 "review_status": "pending", "is_rag_chunk": False})
        else:
            # Avoid hallucinating section boundaries; page-level staging until human semantic-grouping review.
            for i, text in enumerate(page_texts):
                sections.append({"section_id": f"{document_id}::page_{i+1:04d}", "document_id": document_id,
                                 "section_title": f"페이지 {i+1} (의미 단위 검수 필요)", "program_name": None,
                                 "page_start": i+1, "page_end": i+1, "text": text,
                                 "section_method": "page_fallback_needs_semantic_grouping", "review_status": "pending", "is_rag_chunk": False})
        doc.close()
    atomic_write_jsonl(staging / "pdf_pages.jsonl", pages)
    atomic_write_jsonl(staging / "pdf_tables.jsonl", tables)
    atomic_write_jsonl(processed / "source_documents.jsonl", documents)
    atomic_write_jsonl(processed / "guideline_sections.jsonl", sections)
    write_csv(validation / "pdf_review_queue.csv", pdf_review,
              ["document_id", "file_name", "page_number", "reason"])
    return {"pdf_count": len(documents), "pdf_pages": len(pages), "pdf_sections": len(sections), "pdf_tables_detected": len(tables),
            "pages_for_visual_review": len(pdf_review), "all_sections_review_pending": True, "pdf_source_availability": "present" if pdfs else "missing"}


def normalized_title(s: Any) -> str:
    s = clean(s) or ""
    s = re.sub(r"[\s\-·\[\](){}]+", "", s).lower()
    return s.replace("제도", "") if s.endswith("제도") else s


def match_candidates(policies: list[dict[str, Any]], sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate conservative, unapproved policy->PDF candidate relationships.

    This is NOT an authoritative match; only a human can approve.
    The exact policy title must appear in a heading or the extracted source text.
    """
    candidates = []
    prepared = [(sec, normalized_title(sec.get("section_title")), (sec.get("text") or "")[:8000]) for sec in sections]
    for p in policies:
        title = clean(p.get("title"))
        if not title or len(title) < 4:
            continue
        key = normalized_title(title)
        matches = []
        for sec, heading, content in prepared:
            if len(key) >= 4 and key in heading:
                method = "section_heading_title_mention"
            elif len(title) >= 5 and title in content:
                method = "section_source_text_exact_mention"
            else:
                continue
            matches.append({"policy_id": p["policy_id"], "section_id": sec["section_id"],
                            "relation_type": "related_candidate", "match_method": method,
                            "match_confidence": None, "review_status": "pending",
                            "review_note": "Text similarity only. Verify program, publisher, target, local scope and year; no automatic approval."})
            if len(matches) >= 5:
                break
        candidates.extend(matches)
    return candidates


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    staging, processed, validation = [root / "data" / x for x in ("staging", "processed", "validation")]
    for x in (staging, processed, validation):
        x.mkdir(parents=True, exist_ok=True)
    raw = root / "data" / "raw" / "welfare"
    list_candidates = [raw / "welfare_list.json", root / "data" / "raw" / "api" / "welfare_list.json"]
    list_path = next((x for x in list_candidates if x.is_file()), None)
    if not list_path:
        raise SystemExit("Missing welfare_list.json (expected data/raw/welfare/ or data/raw/api/)")
    # XML source directories support original branch as well as flat dev branch.
    xml_candidates = [raw / "details", root / "data" / "raw" / "api", root / "data" / "raw" / "api" / "welfare" / "details"]
    files = {p.stem: p for d in xml_candidates if d.exists() for p in sorted(d.glob("WLF*.xml"))}
    listing = json.loads(list_path.read_text(encoding="utf-8-sig"))
    if not isinstance(listing, list):
        raise SystemExit("Central welfare_list.json must be a JSON array")
    issues, details, policies = [], [], []
    list_ids = set()
    for item in listing:
        if not isinstance(item, dict):
            issues.append({"issue": "central_list_invalid_entry", "id": None})
            continue
        sid = clean(item.get("servId"))
        if not sid:
            issues.append({"issue": "central_list_no_id", "id": None})
            continue
        if sid in list_ids:
            issues.append({"issue": "central_list_duplicate_id", "id": sid})
            continue
        list_ids.add(sid)
        record = None
        fp = files.get(sid)
        if fp:
            try:
                record = parse_central_xml(fp)
                details.append({"source_serv_id": sid, "source_file": fp.relative_to(root).as_posix(), "fields": record,
                                "xml_file_sha256": hashlib.sha256(fp.read_bytes()).hexdigest(), "validation_status": "passed"})
            except (ValueError, ET.ParseError) as ex:
                issues.append({"issue": "invalid_xml", "id": sid, "reason": str(ex)})
        policies.append(central_policy(item, record, list_path.relative_to(root), fp.relative_to(root) if fp and record else None))
    for sid in sorted(set(files) - list_ids):
        issues.append({"issue": "orphan_detail_xml", "id": sid})
    atomic_write_jsonl(staging / "central_detail_parsed.jsonl", details)

    local_file = find_local_data(root)
    if local_file:
        for i, item in enumerate(load_local(local_file), 1):
            try:
                policies.append(local_policy(item, local_file.relative_to(root)))
            except ValueError:
                issues.append({"issue": "local_invalid_entry", "row_number": i})
    for policy in policies:
        status, reason = elderly_relevance(policy)
        policy["elderly_relevance_status"] = status
        policy["elderly_relevance_reason"] = reason
        policy["elderly_review_status"] = "pending"
    pids = [p["policy_id"] for p in policies]
    duplicates = [{"issue": "duplicate_policy_id", "id": k} for k, n in Counter(pids).items() if n > 1]
    issues.extend(duplicates)
    atomic_write_jsonl(processed / "policies.jsonl", policies)

    fac_file = root / "data" / "raw" / "api" / "vworld_elderly_welfare_output" / "all_regions_elderly_welfare.json"
    facilities: list[dict[str, Any]] = []
    if fac_file.is_file():
        obj = json.loads(fac_file.read_text(encoding="utf-8-sig"))
        if not isinstance(obj, list):
            raise SystemExit("Expected VWorld JSON array")
        for i, f in enumerate(obj, 1):
            try:
                facilities.append(facility_row(f, fac_file.relative_to(root)))
            except ValueError:
                issues.append({"issue": "facility_invalid_id", "row_number": i})
    fid_counts = Counter(x["facility_id"] for x in facilities)
    for fid, count in fid_counts.items():
        if count > 1:
            issues.append({"issue": "facility_duplicate_id", "id": fid, "count": count})
    facilities = list({x["facility_id"]: x for x in facilities}.values())
    atomic_write_jsonl(processed / "facilities.jsonl", facilities)

    pdfstats = extract_pdfs(root, staging, processed, validation)
    sections = list(read_jsonl(processed / "guideline_sections.jsonl"))
    candidates = match_candidates(policies, sections)
    write_csv(processed / "policy_source_links.csv", candidates,
              ["policy_id", "section_id", "relation_type", "match_method", "match_confidence", "review_status", "review_note"])
    write_csv(validation / "link_review_queue.csv", candidates,
              ["policy_id", "section_id", "relation_type", "match_method", "match_confidence", "review_status", "review_note"])
    missing = [{"policy_id": p["policy_id"], "source_type": p["source_type"], "source_serv_id": p["source_serv_id"],
                "title": p["title"], "missing_reason": "detail_not_collected"} for p in policies if not p["detail_fetched"]]
    write_csv(validation / "missing_detail_policies.csv", missing,
              ["policy_id", "source_type", "source_serv_id", "title", "missing_reason"])
    elderly_rows = [{"policy_id": p["policy_id"], "title": p.get("title"),
                     "life_stages_raw": p.get("life_stages_raw"),
                     "elderly_relevance_status": p["elderly_relevance_status"],
                     "elderly_relevance_reason": p["elderly_relevance_reason"],
                     "review_status": "pending"} for p in policies]
    write_csv(validation / "elderly_relevance_review.csv", elderly_rows,
              ["policy_id", "title", "life_stages_raw", "elderly_relevance_status", "elderly_relevance_reason", "review_status"])
    title_map = defaultdict(list)
    for policy in policies:
        if policy.get("title"):
            title_map[normalized_title(policy["title"])].append(policy)
    same_title = []
    for key, matches in title_map.items():
        if key and len(matches) > 1:
            for m in matches:
                same_title.append({"normalized_title": key, "policy_id": m["policy_id"],
                                   "source_type": m["source_type"], "sido_name": m["sido_name"],
                                   "review_status": "pending", "note": "Identical normalized title does not prove same policy"})
    write_csv(validation / "same_title_review.csv", same_title,
              ["normalized_title", "policy_id", "source_type", "sido_name", "review_status", "note"])
    missing_important = []
    for p in policies:
        for field in ("target_text", "selection_criteria_text", "benefit_text", "application_text", "source_url"):
            if p.get(field) is None:
                missing_important.append({"policy_id": p["policy_id"], "source_type": p["source_type"], "field": field, "detail_fetched": p["detail_fetched"]})
    write_csv(validation / "missing_fields.csv", missing_important,
              ["policy_id", "source_type", "field", "detail_fetched"])
    invalid_urls = [{"policy_id": p["policy_id"], "source_url": p.get("source_url"),
                     "reason": "invalid_url_format_or_missing"} for p in policies if not p["source_url_format_valid"]]
    write_csv(validation / "invalid_source_urls.csv", invalid_urls,
              ["policy_id", "source_url", "reason"])
    region_pending = [{"policy_id": p["policy_id"], "sido": p["sido_name"], "sigungu": p["sigungu_name"],
                       "scope": p["region_scope"], "reason": "not_verified"} for p in policies if p["region_validation_status"] != "approved"]
    write_csv(validation / "region_review_queue.csv", region_pending,
              ["policy_id", "sido", "sigungu", "scope", "reason"])
    write_csv(validation / "duplicates.csv", duplicates,
              ["issue", "id"])
    write_csv(validation / "source_issues.csv", issues,
              ["issue", "id", "reason", "row_number", "count"])
    atomic_write_jsonl(validation / "conflicts.jsonl", [])  # must not fabricate conflicts
    coverage = Counter((p["source_type"], p["quality_status"]) for p in policies)
    by_region = Counter((p.get("sido_name") or "미확인") for p in policies)
    report = {
        "report_type": "RAG_pre_splitting_data_validation", "run_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": ".", "scope": "before_rag_splitting", "central_list_count": len(list_ids),
        "central_valid_xml": len(details), "central_missing_xml": len(list_ids)-len(details),
        "local_input_found": bool(local_file), "local_input_file": local_file.relative_to(root).as_posix() if local_file else None,
        "facilities_input_found": fac_file.is_file(), "central_input_file": list_path.relative_to(root).as_posix(),
        "policy_count": len(policies), "unique_policy_ids": len(set(pids)),
        "by_source_quality": {f"{a}|{b}": n for (a,b),n in sorted(coverage.items())},
        "policy_counts_by_sido": dict(by_region),
        "detail_missing_count": len(missing), "field_missing_count": dict(Counter(i["field"] for i in missing_important)),
        "facility_count": len(facilities), "facility_region_counts": dict(Counter(x.get("sido_name") or "미확인" for x in facilities)),
        "facility_invalid_coordinates": sum(x["latitude"] is None or x["longitude"] is None for x in facilities),
        "duplicate_policy_id_count": len(duplicates), "source_issue_count": len(issues),
        "pending_region_review": len(region_pending), "pending_policy_pdf_links": len(candidates),
        "invalid_source_url_count": len(invalid_urls),
        "elderly_relevance_counts": dict(Counter(p["elderly_relevance_status"] for p in policies)),
        "same_title_review_count": len(same_title),
        "data_complete_for_splitting": False,
        "pdf": pdfstats,
        "limitations": [
            "Only input files physically present were processed; unavailable PDFs/local welfare/VWorld sources are not treated as completed.",
            "Region scope is not approved automatically. Missing county name does not imply nationwide or province-wide coverage.",
            "Policy-PDF links require human review; there is no automatic approval.",
            "The XML repeat fields are preserved in central_detail_parsed.jsonl, including multi-step application procedure.",
            "PDF sections are preliminary: bookmarks or page-level fallback. Semantic boundaries and tables require human checking.",
            "No RAG splitting, embedding, vector index, PostgreSQL write or external API request was performed."
        ],
    }
    atomic_write_json(validation / "quality_report.json", report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Normalize welfare data and PDF source documents, stopping before RAG splitting")
    p.add_argument("--root", type=Path, default=ROOT_DIR, help="Existing project directory with data/raw/...")
    args=p.parse_args(argv)
    report=run(args.root)
    print(json.dumps({k:v for k,v in report.items() if k in ("policy_count", "central_valid_xml", "central_missing_xml", "detail_missing_count", "facility_count", "pdf")}, ensure_ascii=False, indent=2))
    print("완료: data/staging · data/processed · data/validation (청킹 및 임베딩 미실행)")


if __name__ == "__main__":
    main()
