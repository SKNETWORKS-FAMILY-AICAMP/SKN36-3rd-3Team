"""Append the November 25 Gwangju source snapshot to the November 25 baseline."""
import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rag.chunking.common import validate_chunks
from rag.chunking.fixed_chunker import chunk_fixed
from rag.document_builder import build_policy_documents
from rag.document_validator import validate_documents
from rag.metadata_builder import build_metadata
from welfare_preprocessing.welfare_pipeline.contact_fields import xml_related_groups
from welfare_preprocessing.welfare_pipeline.elderly_filter import classify_elderly
from welfare_preprocessing.welfare_pipeline.normalize_policies import normalize_policy
from welfare_preprocessing.welfare_pipeline.region_selection import classify_region

DISTRICTS = {"동구", "서구", "남구", "북구", "광산구"}
COMBINED = "전남광주통합특별시"
PROCESSED = ROOT / "data/processed/local_welfare/nationwide/final"
RAG = ROOT / "data/rag/nationwide_v2"


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def add_rows(path, rows):
    with path.open("ab") as stream:
        if stream.tell():
            with path.open("rb") as source:
                source.seek(-1, 2)
                if source.read() != b"\n":
                    stream.write(b"\n")
        for row in rows:
            stream.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))


def location_evidence(detail):
    district = detail.get("sggNm")
    if district in DISTRICTS:
        return "sggNm", district
    if district == "광주광역시교육청":
        return "sggNm", district
    if district:
        return None
    for key in ("servNm", "bizChrDeptNm", "sprtTrgtCn", "slctCritCn"):
        value = detail.get(key, "")
        expression = r"^광주광역시|^광주형|^광주다움" if key in {"servNm", "bizChrDeptNm"} else r"광주광역시|광주권역|광주시민"
        if re.search(expression, value) and not re.search(r"전라남도|전남 지역", value):
            return key, value
    return None


def read_source(path):
    with ZipFile(path) as archive:
        listing = {}
        details = {}
        for name in sorted(archive.namelist()):
            if not name.endswith(".xml"):
                continue
            root = ElementTree.fromstring(archive.read(name))
            if root.findtext("resultCode") != "0":
                raise ValueError(f"Unsuccessful XML response: {name}")
            if name.startswith("list/"):
                for entry in root.findall("servList"):
                    listing[entry.findtext("servId")] = {e.tag: e.text for e in entry}
            if name.startswith("details/"):
                fields = defaultdict(list)
                for node in root.iter():
                    if len(node) == 0 and node.text and node.text.strip():
                        fields[node.tag].append(node.text.strip())
                detail = {k: v[0] if len(v) == 1 else json.dumps(v, ensure_ascii=False) for k, v in fields.items()}
                sid = detail["servId"]
                if sid in details or Path(name).stem != sid:
                    raise ValueError(f"Unexpected detail ID: {name}")
                details[sid] = (name, detail | xml_related_groups(root))
    if len(listing) != 555 or len(details) != 515 or not details.keys() <= listing.keys():
        raise ValueError("Unexpected listing or detail snapshot")
    return listing, details


def graph_entity(row, doc):
    meta = doc["metadata"]
    pid = doc["policy_id"]
    return {
        "policy_id": pid,
        "title": row["title"],
        "eligibility_conditions": [
            {"field": key, "operator": None, "value": None, "raw_text": row[key], "review_status": "needs_review"}
            for key in ("target_text", "selection_criteria_text") if row.get(key)
        ],
        "need_tags": meta["need_tags"],
        "need_evidence": meta["need_evidence"],
        "regions": [{"sido_name": meta["sido_name"], "sigungu_name": meta["sigungu_name"],
                     "scope": "unknown", "candidate_scope": meta["region_scope"],
                     "region_status": "needs_review", "review_status": "needs_review"}],
        "agencies": [{"name": meta["department"], "role": "responsible_department", "contact": meta["contact"],
                      "source_id": pid, "review_status": "needs_review"}] if meta["department"] else [],
        "related_policy_ids": [],
        "evidence_refs": [{key: meta[key] for key in ("source_id", "source_url", "source_type")}],
        "approval_status": meta["approval_status"],
        "data_version": meta["data_version"],
    }


def main(zip_path):
    listing, details = read_source(zip_path)
    baseline = read_rows(PROCESSED / "policies_all.jsonl")
    old_ids = {row["policy_id"].split(":")[-1] for row in baseline}
    if len(baseline) != 4427 or len(old_ids) != 4427:
        raise ValueError("Expected the original 4,427-policy baseline")
    version = "gwangju_2026_11_26_" + hashlib.sha256(zip_path.read_bytes()).hexdigest()[:12]
    additions = []
    excluded_existing = []
    for sid, (member, detail) in sorted(details.items()):
        evidence = location_evidence(detail)
        if not evidence:
            continue
        if sid in old_ids:
            excluded_existing.append(sid)
            continue
        raw = {**listing[sid], **{f"detail_{key}": val for key, val in detail.items()}, "detail_fetched": True}
        raw.update(requested_region=COMBINED, detail_source_file=member, source_snapshot_file=zip_path.name)
        policy = normalize_policy(raw)
        field, value = evidence
        policy = classify_region(policy, {})
        if any("conflict" in reason for reason in policy["region_review_reasons"]):
            raise ValueError(f"Review regional conflict for {sid}")
        policy.update(
            sido_name="광주광역시", region_selection_label="gwangju",
            region_selection_source="original_sigungu_metadata" if field == "sggNm" else "source_text_review",
            region_selection_evidence=f"{field}: {value}",
            data_origin="gwangju_combined_api_details",
        )
        additions.append(classify_elderly(policy))
    selected = [row for row in additions if row["elderly_candidate_category"] in {"direct", "indirect"}]
    review = [row for row in additions if row["elderly_candidate_category"] == "review"]
    enriched = []
    for row in selected:
        row = {**row, "data_version": version, "approval_status": "pending"}
        meta = build_metadata(row)
        fields = ("age_min", "age_max", "age_evidence", "age_review_status",
                  "need_tags", "need_evidence", "need_review_status", "region_status")
        enriched.append({**row, **{key: meta[key] for key in fields}})
    docs = build_policy_documents(enriched)
    validate_documents(docs)
    chunks = [chunk for doc in docs for chunk in chunk_fixed(doc, chunk_size=800, overlap=150)]
    graphs = [graph_entity(row, doc) for row, doc in zip(enriched, docs, strict=True)]
    meta_review = [
        {**{key: doc["metadata"][key] for key in ("title", "region_status", "age_evidence", "need_evidence", "data_version")},
         "policy_id": doc["policy_id"], "review_status": "pending"} for doc in docs
    ]
    all_docs = read_rows(RAG / "policy_documents.jsonl") + docs
    all_chunks = read_rows(RAG / "policy_chunks.jsonl") + chunks
    pdf_chunks = read_rows(RAG / "guideline_chunks.jsonl")
    checked = validate_chunks(all_chunks, all_docs, "fixed")
    assert not checked["errors"] and checked["max_chunk_chars"] <= 800
    assert len({c["id"] for c in all_chunks + pdf_chunks}) == len(all_chunks + pdf_chunks)
    assert len({c["chunk_id"] for c in all_chunks + pdf_chunks}) == len(all_chunks + pdf_chunks)
    validate_documents(all_docs)
    assert {g["policy_id"] for g in read_rows(RAG / "policy_graph_entities.jsonl") + graphs} == {
        d["policy_id"] for d in all_docs
    }

    report = json.loads((RAG / "metadata_validation_report.json").read_text())
    report["gwangju_update"] = {
        "data_version": version, "source": zip_path.name, "source_detail_count": len(details),
        "policies": len(additions), "by_district": dict(Counter(row["sigungu_name"] or "시 단위" for row in additions)),
        "elderly_candidates": len(selected), "chunks": len(chunks), "existing_ids_skipped": excluded_existing,
    }
    report["input"].update(total_policies=len(baseline + additions), elderly_candidates=len(all_docs))
    report["documents"]["policy"] = len(all_docs)
    report["chunks"].update(policy=len(all_chunks), total=len(all_chunks) + len(pdf_chunks))
    report["neo4j"]["policy_graph_entities"] = len(all_docs)
    report["validation"]["policy_chunk_validation"] = checked
    report["limitations"][0] = "광주 상세 확보분 중 지역 근거 확인 건을 반영했으며 신규 전남 전체 및 상세 미확보 정책은 미포함"

    quality = json.loads((PROCESSED / "quality_report.json").read_text())
    all_policies = baseline + additions
    groups = Counter(row["elderly_candidate_category"] for row in all_policies)
    contacts = Counter(row["contact_status"] for row in all_policies)
    quality["dataset_scope"].update(total_policies=len(all_policies), gwangju_added=len(additions),
                                    region_groups=17, gwangju_included=True)
    quality["validation"].update({"전체 정책 수": len(all_policies), "고유 정책 ID": len(all_policies),
                                  "광주 정책": len(additions), "원본 기반 문의처": contacts["source_group_confirmed"],
                                  "노인 관련 검색 후보": len(all_docs)})
    quality["elderly_category_counts"] = groups
    quality["contact_status_counts"] = contacts
    for field in quality["field_quality"]:
        added = sum(row.get(field["필드"]) not in (None, "", [], {}) for row in additions)
        field["전체"] += len(additions)
        field["정상"] += added
        field["결측"] = field["전체"] - field["정상"]
        field["결측률(%)"] = round(100 * field["결측"] / field["전체"], 2)

    for directory, outputs in (
        (PROCESSED, {"policies_all": additions, "policies_elderly_candidates": selected, "policies_review": review}),
        (RAG, {"policy_metadata_input": enriched, "policy_documents": docs, "policy_chunks": chunks,
               "policy_graph_entities": graphs, "metadata_review": meta_review}),
    ):
        for name, rows in outputs.items():
            add_rows(directory / f"{name}.jsonl", rows)
    for path, payload in ((RAG / "metadata_validation_report.json", report), (PROCESSED / "quality_report.json", quality)):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    csv_path = PROCESSED / "field_quality_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(quality["field_quality"][0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(quality["field_quality"])
    print(json.dumps(report["gwangju_update"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    main(parser.parse_args().snapshot)
