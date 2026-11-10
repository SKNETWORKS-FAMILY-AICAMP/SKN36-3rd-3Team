#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SKN36 정책(중앙+지자체) / VWorld 시설 / PDF 섹션 자동 Splitting.

사용:
  python SKN36_auto_splitting.py --input-dir "C:\\...\\splitting_inputs"
  python SKN36_auto_splitting.py --input-dir ./splitting_inputs --output-dir ./splitting_output

입력 파일 4개 필수 / 5번째 노령층 분권 PDF 혹은 JSONL은 선택(추가하면 자동 처리).
모든 변환은 로컬에서 수행하며 API/Neo4j/Qdrant에 연결하거나 쓰지 않습니다.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "skn36-chunks-v3-table-safe-preembedding"
POLICY_MAX_BODY_CHARS = 650  # 기존 노트북 설정 유지
PDF_MAX_BODY_CHARS = 700     # 기존 노트북 설정 유지
OVERLAP_CHARS = 90          # 기존 노트북 설정 유지

REPO = "SKNETWORKS-FAMILY-AICAMP/SKN36-3rd-3Team"
SOURCE_BRANCHES = {
    "central": "feature/pre-splitting-ready",
    "local": "feature/10-api-data-processing",
    "facility": "feature/10-api-data-processing",
    "pdf_sections": "preprocess_pdf_01",
    "elderly_pdf_raw": "feature/10-api-data-processing",  # 같은 브랜치에 PDF 원본 5종 존재
}
OBSERVED_HEADS = {  # 조사 시점 참조값; 실제 다운로드한 파일의 해시는 별도 기록
    "central": "f7833d6646e52a3fb92820ab06c26fd529e5d5c0",
    "local": "765d7f6d976c36f17736f56bc88d97704ca0e910",
    "facility": "765d7f6d976c36f17736f56bc88d97704ca0e910",
    "pdf_sections": "12488343d444405232e407f34f6a51ce94159751",
    "elderly_pdf_raw": "765d7f6d976c36f17736f56bc88d97704ca0e910",
}
EXPECTED_COUNTS = {"central": 461, "local": 1485, "facility": 164, "pdf_sections": 1189}

# 같은 폴더에 넣거나, 이 폴더 하위의 여러 브랜치별 폴더에 나누어 넣어도 됩니다.
FILE_PATTERNS = {
    "central": ["policies.jsonl"],
    "local": ["welfare_all_full_*.jsonl"],
    "facility": ["all_regions_elderly_welfare.json"],
    "pdf_sections": ["guideline_sections_filtered.jsonl"],
    "elderly_sections": ["guideline_sections_elderly.jsonl", "guideline_sections_elderly_only.jsonl"],
    "elderly_pdf_raw": ["*복지서비스_분권(노령층).pdf", "*복지서비스*분권*노령층*.pdf"],
    "pdf_basic_raw": ["*기초연금*사업안내*.pdf"],
    "pdf_senior_1_raw": ["*노인보건복지사업안내*1권*.pdf"],
    "pdf_senior_2_raw": ["*노인보건복지사업안내*2권*.pdf"],
    "pdf_summary_raw": ["*복지서비스*표지합본*최종*.pdf"],
}
PDF_SOURCE_CANDIDATES = {
    "2026_나에게_힘이_되는_복지서비스": "2026 나에게 힘이 되는 복지서비스_표지합본 최종.pdf",
    "2026_노인보건복지사업안내_1권": "2026_노인보건복지사업안내(1권).pdf",
    "2026_노인보건복지사업안내_2권": "2026_노인보건복지사업안내(2권).pdf",
    "2026_기초연금_사업안내": "2026년 기초연금 사업안내.pdf",
    "2026_나에게_힘이_되는_복지서비스_노령층_분권_raw_pages": "2026 나에게 힘이 되는 복지서비스_분권(노령층).pdf",
}


@dataclass
class Config:
    input_dir: Path
    output_dir: Path | None = None
    require_fifth_pdf: bool = False
    strict_counts: bool = False
    tokenizer_name: str = ""
    max_embedding_tokens: int = 512
    exclude_clear_toc: bool = True


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    s = unicodedata.normalize("NFC", str(value)).replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    return "\n".join(re.sub(r"[ \t]+", " ", line).rstrip() for line in s.split("\n")).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_inputs(root: Path) -> dict[str, Path | None]:
    if not root.is_dir():
        raise FileNotFoundError(f"입력 폴더가 없습니다: {root}")
    found: dict[str, Path | None] = {}
    for name, patterns in FILE_PATTERNS.items():
        unique: dict[str, Path] = {}
        for pat in patterns:
            for file in root.rglob(pat):
                if file.is_file() and not any(part.startswith(".") for part in file.relative_to(root).parts):
                    unique[str(file.resolve())] = file
        matches = sorted(unique.values(), key=lambda p: str(p))
        if len(matches) > 1:
            raise ValueError(f"{name} 입력 파일이 여러 개 발견됨. 중복 없는 입력 폴더를 사용하세요:\n" + "\n".join(str(x) for x in matches[:10]))
        found[name] = matches[0] if matches else None
    missing = [key for key in ("central", "local", "facility", "pdf_sections") if found[key] is None]
    if missing:
        lines = [f"필수 입력이 없습니다: {', '.join(missing)}", f"지정 폴더: {root}", "예상 파일명:"]
        lines += [f"- {k}: {FILE_PATTERNS[k][0]}" for k in missing]
        raise FileNotFoundError("\n".join(lines))
    return found


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8-sig") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path.name}:{lineno}행 JSON 오류: {e}") from e
            if not isinstance(row, dict):
                raise ValueError(f"{path.name}:{lineno}행은 JSON 객체여야 합니다.")
            rows.append(row)
    if not rows:
        raise ValueError(f"빈 JSONL 파일: {path}")
    return rows


def read_json_array(path: Path) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError(f"시설 데이터가 객체 배열이 아닙니다: {path}")
    if not rows:
        raise ValueError(f"시설 데이터가 비었습니다: {path}")
    return rows


def check_unique(rows: list[dict], field: str, kind: str) -> None:
    ids = [clean_text(r.get(field)) for r in rows]
    if any(not x for x in ids):
        raise ValueError(f"{kind} {field} 값이 누락됐습니다.")
    duplicates = [x for x, c in Counter(ids).items() if c > 1]
    if duplicates:
        raise ValueError(f"{kind} {field} 중복: {duplicates[:5]}")


def check_count(kind: str, count: int, strict: bool, warnings: list[str]):
    expected = EXPECTED_COUNTS[kind]
    if count != expected:
        msg = f"{kind} 예상 {expected:,}건, 실제 {count:,}건 (데이터 갱신/누락 여부 확인)"
        if strict:
            raise ValueError(msg)
        warnings.append(msg)


def normalize_local(rows: list[dict]) -> list[dict]:
    check_unique(rows, "servId", "지자체 API")
    out = []
    for raw in rows:
        sid = clean_text(raw.get("servId"))
        detail = raw.get("detail_fetched") is True
        def field(key: str, fallback: str | None = None):
            return clean_text(raw.get(key) if raw.get(key) is not None else raw.get(fallback)) or None
        target = field("detail_sprtTrgtCn") if detail else None
        criteria = field("detail_slctCritCn") if detail else None
        benefit = field("detail_alwServCn") if detail else None
        application = field("detail_aplyMtdCn") if detail else None
        title = field("detail_servNm", "servNm") or field("servNm")
        if not title:
            raise ValueError(f"지자체 서비스명이 없습니다: {sid}")
        out.append({
            "policy_id": "local:" + sid, "source_type": "local_welfare_api",
            "source_serv_id": sid, "title": title,
            "summary": field("detail_servDgst", "servDgst") or field("servDgst"),
            "sido_name": field("detail_ctpvNm", "ctpvNm") or field("ctpvNm"),
            "sigungu_name": field("detail_sggNm", "sggNm") or field("sggNm"),
            # 시군구 명칭만으로 정확한 수급 가능 지역을 확정하지 않음
            "region_scope": "unknown", "region_validation_status": "pending",
            "target_text": target, "selection_criteria_text": criteria,
            "benefit_text": benefit, "application_text": application,
            "application_steps": [],
            "department": field("detail_bizChrDeptNm", "bizChrDeptNm"),
            "contact": field("detail_inqNum", "inqNum"), "source_url": field("servDtlLink"),
            "updated_at_source": field("detail_lastModYmd", "lastModYmd"),
            "start_date": field("detail_enfcBgngYmd") if detail else None,
            "end_date": field("detail_enfcEndYmd") if detail else None,
            "life_stages_raw": field("detail_lifeNmArray", "lifeNmArray"),
            "target_groups_raw": field("detail_trgterIndvdlNmArray", "trgterIndvdlNmArray"),
            "themes_raw": field("detail_intrsThemaNmArray", "intrsThemaNmArray"),
            "benefit_frequency_raw": field("detail_sprtCycNm", "sprtCycNm"),
            "detail_fetched": detail,
            "quality_status": ("detail_complete" if all([target, criteria, benefit, application]) else "detail_partial") if detail else "list_only",
            "source_coverage": "api_only", "elderly_relevance_status": "unclassified_needs_review",
            "elderly_review_status": "pending", "policy_relation_review_status": "unlinked",
            "source_file_list": "data/raw/api/local_welfare_service_outputs/welfare_all_full_20261107_103452.jsonl",
            "needs_detail_collection": not detail, "region_coverage_hint_only": field("ctpvNm"),
        })
    return out


def normalize_facilities(rows: list[dict]) -> list[dict]:
    check_unique(rows, "_feature_id", "VWorld 시설")
    out = []
    for raw in rows:
        fid = clean_text(raw["_feature_id"])
        lat, lon = raw.get("latitude"), raw.get("longitude")
        if lat is not None and (not isinstance(lat, (int, float)) or not -90 <= lat <= 90):
            raise ValueError(f"시설 위도값 오류: {fid}")
        if lon is not None and (not isinstance(lon, (int, float)) or not -180 <= lon <= 180):
            raise ValueError(f"시설 경도값 오류: {fid}")
        name = clean_text(raw.get("fac_nam"))
        if not name:
            raise ValueError(f"시설명 누락: {fid}")
        out.append({
            "facility_id": "vworld:" + fid, "source_feature_id": fid,
            "title": name, "category": clean_text(raw.get("cat_nam")) or None,
            "region": clean_text(raw.get("region")) or None,
            "address_road": clean_text(raw.get("fac_n_add")) or None,
            "address_lot": clean_text(raw.get("fac_o_add")) or None,
            "phone": clean_text(raw.get("fac_tel")) or None,
            "latitude": lat, "longitude": lon,
            "source_type": "vworld_elderly_welfare",
            "region_validation_status": "pending",
        })
    return out


def extract_elderly_pdf_pages(path: Path) -> list[dict]:
    """5번째 PDF가 아직 의미 단위 JSONL로 전처리되지 않아 페이지별 임시 섹션을 생성합니다.
    표/레이아웃과 원문 페이지 대조는 반드시 사람 검수가 필요합니다.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise ImportError("5번째 원본 PDF를 자동 추출하려면 'pip install pymupdf'를 먼저 실행하세요.") from e
    rows = []
    with fitz.open(str(path)) as doc:
        if doc.is_encrypted:
            raise ValueError("5번째 PDF가 암호화되어 있어 텍스트를 추출할 수 없습니다.")
        for i, page in enumerate(doc, 1):
            body = page.get_text("text", sort=True)
            rows.append({
                "section_id": f"elderly_leaflet_2026_raw_p{i:04d}",
                "source": "2026_나에게_힘이_되는_복지서비스_노령층_분권_raw_pages",
                "title": "2026 나에게 힘이 되는 복지서비스 — 노령층 분권",
                "section": f"페이지 {i} (임시 추출·검수 전)",
                "subsection": None, "content": body,
                "page_start": i, "page_end": i, "images": [],
                "extraction_method": "pymupdf_page_text_fallback",
                "review_status": "pending",
            })
    return rows


def validate_pdf_sections(rows: list[dict]):
    check_unique(rows, "section_id", "PDF 섹션")
    for r in rows:
        for field in ("source", "content", "page_start", "page_end"):
            if field not in r:
                raise ValueError(f"PDF 섹션 {r['section_id']} 필드 {field} 누락")
        st, en = r["page_start"], r["page_end"]
        if type(st) is not int or type(en) is not int or st < 1 or en < st:
            raise ValueError(f"PDF 섹션 {r['section_id']} 페이지 오류: {st}~{en}")


def split_windows(text: str, max_chars: int, overlap: int):
    """기존 노트북 분할 알고리즘·경계 우선순위·오버랩을 그대로 사용."""
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [(0, len(text), text)]
    result = []
    pos, n = 0, len(text)
    while pos < n:
        end = min(pos + max_chars, n)
        if end < n:
            low = pos + int(max_chars * 0.70)
            for sep in ("\n\n", "\n", "。", ". ", "! ", "? ", " "):
                k = text.rfind(sep, low, end)
                if k >= 0:
                    candidate = k + len(sep)
                    if candidate > pos + overlap + 1:
                        end = candidate
                        break
        raw_piece = text[pos:end]
        lead = len(raw_piece) - len(raw_piece.lstrip())
        trail = len(raw_piece) - len(raw_piece.rstrip())
        piece = raw_piece.strip()
        if piece:
            result.append((pos + lead, end - trail, piece))
        if end >= n:
            break
        next_pos = end - overlap
        if next_pos <= pos:
            raise RuntimeError("분할 창 이동 실패: 최대 길이·오버랩 설정을 확인하세요")
        pos = next_pos
    return result


def stable_point_id(chunk_id: str) -> str:
    # 이전 노트북의 UUID 생성 방식을 유지: 같은 원본·청크는 같은 Qdrant/Neo4j ID
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "skn36/v1/" + chunk_id))


def make_metadata(**kwargs) -> dict:
    return {k: v for k, v in kwargs.items() if isinstance(v, (str, bool, int, float)) and (not isinstance(v, str) or v.strip())}


def make_chunk(chunk_id, record_type, title, heading, body, offset_start, offset_end, meta, extra=None):
    prefix = f"문서: {clean_text(title)[:120]}\n주제: {clean_text(heading)[:150]}\n"
    body = clean_text(body)
    chunk = {
        "schema_version": SCHEMA_VERSION, "id": stable_point_id(chunk_id),
        "chunk_id": chunk_id, "record_type": record_type,
        "text": prefix + body, "body_text": body,
        "body_offset_start": offset_start, "body_offset_end": offset_end,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "metadata": make_metadata(**meta),
    }
    if extra:
        chunk.update(extra)
    return chunk


def collect_application_steps(policy):
    steps = policy.get("application_steps") or []
    if not isinstance(steps, list):
        return ""
    pieces = []
    for i, step in enumerate(steps, 1):
        if isinstance(step, dict):
            title = clean_text(step.get("servSeDetailNm"))
            link = clean_text(step.get("servSeDetailLink"))
            if title or link:
                pieces.append(f"{i}. {title}: {link}".strip())
    return "\n".join(pieces)


def policy_sections(policy):
    summary = clean_text(policy.get("summary"))
    sections = [("overview", "정책 개요", f"요약: {summary}" if summary else "")]
    eligibility = []
    for label, field in [("지원대상", "target_text"), ("선정기준", "selection_criteria_text")]:
        val = clean_text(policy.get(field))
        if val:
            eligibility.append(f"{label}: {val}")
    if eligibility:
        sections.append(("eligibility", "지원대상 및 선정기준", "\n\n".join(eligibility)))
    benefit = clean_text(policy.get("benefit_text"))
    if benefit:
        sections.append(("benefits", "지원내용 및 혜택", f"지원내용: {benefit}"))
    application = clean_text(policy.get("application_text")) or collect_application_steps(policy)
    if application:
        sections.append(("application", "신청방법 및 절차", f"신청방법: {application}"))
    if not any(body for _, _, body in sections):
        # 목록마저 요약이 없는 서비스는 구조용 카드만 남기고 임베딩 후보에서 제외합니다.
        sections = [("overview", "정책명만 확인됨", "상세내용 미확보: 공식 출처에서 확인 필요")]
    return [(k, heading, body) for k, heading, body in sections if body]


def build_policy_chunks(rows):
    out = []
    for p in sorted(rows, key=lambda x: x["policy_id"]):
        pid = p["policy_id"]
        title = clean_text(p.get("title")) or pid
        detail = p.get("detail_fetched") is True
        content_fields = any(clean_text(p.get(f)) for f in ("summary", "target_text", "selection_criteria_text", "benefit_text", "application_text"))
        for kind, heading, body in policy_sections(p):
            for n, (start, end, part) in enumerate(split_windows(body, POLICY_MAX_BODY_CHARS, OVERLAP_CHARS), 1):
                chunk_id = f"policy::{pid}::{kind}::{n:04d}"
                meta = dict(record_type="policy", policy_id=pid, source_type=clean_text(p.get("source_type")),
                    source_serv_id=clean_text(p.get("source_serv_id")), title=title,
                    section_kind=kind, detail_fetched=detail,
                    eligibility_verified=False,
                    region_scope=clean_text(p.get("region_scope")) or "unknown",
                    region_validation_status=clean_text(p.get("region_validation_status")) or "pending",
                    sido_name=clean_text(p.get("sido_name")), sigungu_name=clean_text(p.get("sigungu_name")),
                    quality_status=clean_text(p.get("quality_status")) or "unknown",
                    source_url=clean_text(p.get("source_url")),
                    elderly_relevance_status=clean_text(p.get("elderly_relevance_status")),
                    section_index=n, include_in_embedding=content_fields,
                    eligibility_review_status="pending", region_filter_allowed=False,
                    detail_level="detail" if detail else "list_only",
                    suitable_for_automated_eligibility_decision=False)
                out.append(make_chunk(chunk_id, "policy", title, heading, part, start, end, meta,
                                      {"policy_id": pid, "section_kind": kind}))
    return out


def build_facility_chunks(rows):
    out = []
    for f in sorted(rows, key=lambda x: x["facility_id"]):
        fid = f["facility_id"]
        parts = [(label, clean_text(f.get(field))) for label, field in [
            ("시설명", "title"), ("시설유형", "category"), ("지역", "region"),
            ("도로명주소", "address_road"), ("지번주소", "address_lot"), ("연락처", "phone")]]
        body = "\n".join(f"{label}: {value}" for label, value in parts if value)
        for n, (start, end, part) in enumerate(split_windows(body, POLICY_MAX_BODY_CHARS, OVERLAP_CHARS), 1):
            chunk_id = f"facility::{fid}::info::{n:04d}"
            meta = dict(record_type="facility", facility_id=fid, source_type="vworld_elderly_welfare",
                        title=f["title"], region=clean_text(f.get("region")),
                        latitude=f.get("latitude"), longitude=f.get("longitude"),
                        region_validation_status="pending", chunk_index=n,
                        include_in_embedding=True)
            out.append(make_chunk(chunk_id, "facility", f["title"], "시설 위치·연락처", part, start, end, meta,
                                  {"facility_id": fid}))
    return out


def looks_like_toc(row):
    heading = " ".join(clean_text(row.get(k)) for k in ("title", "section", "subsection"))
    return bool(re.search(r"(가나다순\s*서비스\s*목록|전체\s*목차|복지서비스\s*찾아보기)", heading))


TABLE_LINE = re.compile(r"^\s*\|.+\|\s*$")
TABLE_SEPARATOR = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
FINANCIAL_PATTERN = re.compile(r"(?:선정기준액|소득인정액|기준\s*중위소득|\d[\d,]*(?:\.\d+)?\s*(?:만\s*)?원|\d{4}년|\d+(?:\.\d+)?\s*%)")


def _table_cells(line):
    return [clean_text(x).replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
            for x in line.strip().strip("|").split("|")]


def split_pdf_semantically(text, max_chars=PDF_MAX_BODY_CHARS, section_heading=""):
    """Markdown 표의 행/열 레이블을 재부착한다. 단일 셀이 너무 길면 열 이름을 반복.

    반환 start/end는 항상 원본 section.content 내 위치를 가리킨다. 표의 text는 변환된
    검색 카드이므로 original range와 길이가 다를 수 있다(별도 offset_mode 표시).
    """
    text = clean_text(text)
    lines = text.splitlines(keepends=True)
    pos = 0
    spans = []
    for line in lines:
        spans.append((pos, pos + len(line), line))
        pos += len(line)
    if not spans:
        return []
    units=[]
    i = 0
    prior = []
    while i < len(spans):
        st, en, line = spans[i]
        if TABLE_LINE.match(line):
            j=i
            while j < len(spans) and TABLE_LINE.match(spans[j][2]):
                j+=1
            block = spans[i:j]
            if len(block)>=3 and TABLE_SEPARATOR.match(block[1][2]):
                headers=_table_cells(block[0][2])
                data_rows=block[2:]
                # PDF 추출기가 '열 1/열 2/열 3' 가짜 헤더를 생성한 경우,
                # 실제 첫 데이터 행(2025년 현행/2026년 개정안)을 헤더로 승격.
                if data_rows and all(re.fullmatch(r"열\s*\d+",h) for h in headers):
                    candidate=_table_cells(data_rows[0][2])
                    if len(candidate)==len(headers) and "2025년" in " ".join(candidate) and "2026년" in " ".join(candidate):
                        headers=[x.replace("\n"," ")[:100] for x in candidate]
                        data_rows=data_rows[1:]
                prior_nonempty=[x.strip() for x in prior if x.strip()]
                nearby=next((a for a in reversed(prior_nonempty[-8:])
                            if len(a)>4 and len(a)<120 and not re.fullmatch(r"[ivxlcdmIVXLCDM]+",a)), "")
                caption=nearby or clean_text(section_heading)[:105] or "표(원문 제목 확인 필요)"
                caption=caption.replace("<br>"," ")[:105]
                for row_index, (r_st,r_en,row_line) in enumerate(data_rows,1):
                    cells=_table_cells(row_line)
                    if not any(cells):continue
                    key=(cells[0] or "미지정 행")[:90]
                    base=f"표 문맥: {caption}\n행: {key}\n"
                    col_items=[]
                    for col_i in range(1,max(len(headers),len(cells))):
                        h=(headers[col_i] if col_i<len(headers) else f"열 {col_i+1}").replace("\n"," ")[:100]
                        v=cells[col_i] if col_i<len(cells) else ""
                        if v.strip():col_items.append((h,v))
                    if not col_items:
                        col_items=[(headers[0] if headers else "값",cells[0])]
                    buffer=""
                    col_labels=[]
                    segment_number=0
                    def emit():
                        nonlocal buffer, segment_number, col_labels
                        if not buffer.strip():return
                        segment_number+=1
                        units.append({"start":r_st,"end":r_en,"body":base+buffer.strip(),
                            "content_kind":"markdown_table_row", "table_row_index":row_index,
                            "table_caption":caption, "table_column_labels":list(col_labels),
                            "offset_mode":"source_table_row_range", "table_row_sha256":hashlib.sha256(row_line.encode("utf-8")).hexdigest(),
                            "table_segment_number":segment_number,
                            "risk_flags":["table_original_page_review_required"]})
                        buffer="";col_labels=[]
                    for col_label,value in col_items:
                        value=value.strip()
                        prefix=f"{col_label}: "
                        item=prefix+value+"\n"
                        if len(base+buffer+item)<=max_chars:
                            buffer+=item;col_labels.append(col_label);continue
                        emit()
                        if len(base+item)<=max_chars:
                            buffer=item;col_labels.append(col_label);continue
                        # 긴 셀을 분할할 때도 표 제목·행 이름·열 이름은 모든 청크에 반복.
                        budget=max_chars-len(base)-len(prefix)-12
                        if budget<100:
                            raise ValueError("표 열/행 컨텍스트가 너무 깁니다: "+caption)
                        for _,_,part in split_windows(value,budget,0):
                            body=base+prefix+part
                            if len(body)>max_chars:raise ValueError("표 분할 길이 초과")
                            segment_number+=1
                            units.append({"start":r_st,"end":r_en,"body":body,
                                "content_kind":"markdown_table_row", "table_row_index":row_index,
                                "table_caption":caption,"table_column_labels":[col_label],
                                "offset_mode":"source_table_row_range", "table_row_sha256":hashlib.sha256(row_line.encode("utf-8")).hexdigest(),
                                "table_segment_number":segment_number,
                                "risk_flags":["table_original_page_review_required","long_table_cell_split_with_repeated_header"]})
                    emit()
                prior.extend(x[2] for x in block)
                i=j
                continue
        # 자유 텍스트는 다음 Markdown 표 블록 앞에서 끊어서 처리한다.
        j=i+1
        while j<len(spans):
            if TABLE_LINE.match(spans[j][2]) and j+2<len(spans) and TABLE_SEPARATOR.match(spans[j+1][2]):
                break
            j+=1
        raw=text[spans[i][0]:spans[j-1][1]]
        for a,b,part in split_windows(raw,max_chars,OVERLAP_CHARS):
            units.append({"start":spans[i][0]+a,"end":spans[i][0]+b,"body":part,
                "content_kind":"prose", "offset_mode":"normalized_section_text", "risk_flags":[]})
        prior.extend(x[2] for x in spans[i:j])
        i=j
    return units


def find_original_pdf_paths(files):
    mapping={"2026_기초연금_사업안내":files.get("pdf_basic_raw"),
        "2026_노인보건복지사업안내_1권":files.get("pdf_senior_1_raw"),
        "2026_노인보건복지사업안내_2권":files.get("pdf_senior_2_raw"),
        "2026_나에게_힘이_되는_복지서비스":files.get("pdf_summary_raw"),
        "2026_나에게_힘이_되는_복지서비스_노령층_분권_raw_pages":files.get("elderly_pdf_raw")}
    return {k:v for k,v in mapping.items() if v}


def _page_anchor_key(text):
    # 원문/추출 텍스트의 공백·줄바꿈 차이만 흡수; 원문에 없는 문자열은 만들어 매칭하지 않음.
    return re.sub(r"\s+", "", clean_text(text))


def align_source_pages(pdf_chunks, pdf_originals, pdf_sections):
    """원본 PDF가 실제 입력된 경우에만 페이지 텍스트 앵커 확인.

    페이지 범위가 여러 장인데 원본이 없는 경우에는 정확한 단일 페이지를 부여하지 않는다.
    """
    if not pdf_originals:
        return {"raw_pdfs_checked":0,"single_page_text_anchor_matches":0,"multi_page_unresolved":sum(c["metadata"].get("page_start") != c["metadata"].get("page_end") for c in pdf_chunks)}
    try:
        import fitz
    except ImportError as e:
        raise ImportError("원본 PDF 페이지 정밀 매핑에는 PyMuPDF 설치가 필요합니다.") from e
    by_src={}
    for c in pdf_chunks:by_src.setdefault(c["metadata"]["source"],[]).append(c)
    matches=0; unresolved=0
    for src, path in pdf_originals.items():
        if src not in by_src:continue
        with fitz.open(str(path)) as doc:
            cache={}
            def page_key(pg):
                if pg not in cache:
                    cache[pg]=_page_anchor_key(doc[pg-1].get_text("text",sort=True))
                return cache[pg]
            for c in by_src[src]:
                st=c["metadata"]["page_start"];en=c["metadata"]["page_end"]
                if not (1<=st<=en<=len(doc)):
                    c["metadata"]["page_alignment_status"]="range_outside_raw_pdf_review";unresolved+=1;continue
                raw=_page_anchor_key(c["body_text"])
                # 문서 본문은 표 정규화 전에 존재하던 원문과 구조가 달라진다.
                if c["metadata"].get("content_kind")=="markdown_table_row":
                    c["metadata"]["page_alignment_status"]="table_transformed_manual_review";unresolved+=1;continue
                words=re.sub(r"[^0-9a-zA-Z가-힣]", "", raw)
                anchors=[words[k:k+28] for k in (0, max(0,len(words)//2-14), max(0,len(words)-28)) if len(words)>=28]
                anchors=list(dict.fromkeys(a for a in anchors if len(a)>=28))
                candidates=[]
                for page in range(st,en+1):
                    normalized=re.sub(r"[^0-9a-zA-Z가-힣]", "", page_key(page))
                    if len(anchors)>=2 and sum(a in normalized for a in anchors)>=2:
                        candidates.append(page)
                if len(candidates)==1:
                    c["metadata"]["citation_page_candidate"]=candidates[0]
                    c["metadata"]["page_alignment_status"]="unique_text_anchor_candidate_review_required"
                    # 자동 후보일 뿐 공식 인용 승인값이 아님.
                    matches+=1
                else:
                    c["metadata"]["page_alignment_status"]="raw_pdf_text_match_inconclusive"
                    unresolved+=1
    return {"raw_pdfs_checked":len(pdf_originals),"single_page_text_anchor_matches":matches,"chunks_page_alignment_unresolved":unresolved}


def build_pdf_chunks(rows, *, exclude_toc=True, elderly_pdf_path=None):
    chunks, review_queue, registry = [], [], {}
    for s in sorted(rows, key=lambda x: (str(x["source"]), x["page_start"], x["section_id"])):
        sid, source = s["section_id"], clean_text(s["source"])
        content = clean_text(s.get("content"))
        doc_id = "pdf:" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
        if source not in registry:
            registry[source] = {"document_id":doc_id,"source":source,
                "file_name":None,"file_name_candidate":PDF_SOURCE_CANDIDATES.get(source),
                "file_name_verified":False,"source_file_hash":None,
                "source_file_hash_verified":False,"review_status":"pending"}
        raw_fifth = s.get("extraction_method") == "pymupdf_page_text_fallback"
        if raw_fifth and elderly_pdf_path:
            registry[source]["file_name"] = elderly_pdf_path.name
            registry[source]["file_name_verified"] = True
            registry[source]["source_file_hash"] = sha256_file(elderly_pdf_path)
            registry[source]["source_file_hash_verified"] = True
        heading_parts = [clean_text(s.get(k)) for k in ("title", "section", "subsection")]
        heading = " > ".join(x for x in heading_parts if x) or "제목이 확인되지 않은 섹션"
        pstart, pend = s["page_start"], s["page_end"]
        images = s.get("images") or []
        if not isinstance(images, list):images=[images]
        flags=[]
        if len(content)>5000:flags.append("long_section_original")
        if len(content)<80:flags.append("short_section_original")
        if images:flags.append("images_need_review")
        if FINANCIAL_PATTERN.search(content):flags.append("financial_values_need_source_review")
        segments=split_pdf_semantically(content,PDF_MAX_BODY_CHARS,heading)
        table_segments=sum(u["content_kind"]=="markdown_table_row" for u in segments)
        if table_segments:flags.append("markdown_tables_require_source_review")
        if re.search(r"(?m)^\s*- 행\s*\d",content):flags.append("ocr_layout_table_requires_review")
        is_toc=looks_like_toc(s)
        if is_toc:flags.append("toc_or_index")
        if not content:flags.append("empty_pdf_text")
        if raw_fifth:flags.extend(["raw_page_extraction_unreviewed","layout_tables_may_be_incomplete", "possible_overlap_with_general_guide"])
        if pstart!=pend:flags.append("precise_single_citation_page_unresolved")
        if flags:
            review_queue.append({"record_type":"guideline","source_id":sid,"source":source,
                "page_start":pstart,"page_end":pend,"flags":"|".join(flags),
                "table_chunk_count":table_segments})
        for n,u in enumerate(segments,1):
            chunk_id=f"guideline::{sid}::{n:04d}"
            include=not(exclude_toc and is_toc)
            status="single_page_section_not_original_verified" if pstart==pend else "page_range_only_unverified"
            meta=dict(record_type="guideline",document_id=doc_id,section_id=sid,
                source_type="official_pdf_unverified",source=source,title=clean_text(s.get("title")),
                section_title=heading[:400],page_start=pstart,page_end=pend,
                page_range_is_exact_for_chunk=(pstart==pend),
                page_alignment_status=status,image_count=len(images),
                review_status="pending",chunk_index=n,include_in_embedding=include,
                citation_page_approved=False, source_amounts_verified=False,
                content_kind=u["content_kind"],offset_mode=u["offset_mode"],
                extraction_method=clean_text(s.get("extraction_method")),
                table_row_index=u.get("table_row_index"),
                table_segment_number=u.get("table_segment_number"))
            chunk_flags=list(dict.fromkeys(flags+u["risk_flags"]))
            extra={"document_id":doc_id,"section_id":sid,"source_page_range":[pstart,pend],
                "page_range_is_exact_for_chunk":pstart==pend,"original_images":images,
                "review_flags":chunk_flags,"include_in_embedding":include}
            if u["content_kind"]=="markdown_table_row":
                extra.update({"table_caption":u["table_caption"],"table_column_labels":u["table_column_labels"],
                              "table_row_sha256":u["table_row_sha256"]})
            chunks.append(make_chunk(chunk_id,"guideline",source,heading,u["body"],u["start"],u["end"],meta,extra))
    return chunks,review_queue,sorted(registry.values(),key=lambda x:x["source"])


def build_policy_pdf_link_candidates(policies, pdf_sections):
    """원문에 정책명이 문자 그대로 있을 때만 검수 후보 생성. 자동 승인/그래프 관계 생성 금지."""
    index=[]
    for section in pdf_sections:
        heading=" ".join(clean_text(section.get(k)) for k in ("title","section","subsection"))
        content=clean_text(section.get("content"))
        text=re.sub(r"\s+", "", heading+" "+content)
        index.append((section, re.sub(r"[^0-9a-zA-Z가-힣]", "",text)))
    candidates=[]
    for p in policies:
        title=clean_text(p.get("title"))
        key=re.sub(r"[^0-9a-zA-Z가-힣]", "",title)
        if len(key)<5 or key in ("노인복지서비스", "취약계층지원", "생활지원서비스"):
            continue
        matches=[]
        for sec,normalized in index:
            if key in normalized:
                heading=" ".join(clean_text(sec.get(k)) for k in ("title","section","subsection"))
                matches.append((int(key in re.sub(r"[^0-9a-zA-Z가-힣]", "",heading)),sec))
        # 너무 광범위한 용어를 배제하고 수동 검토량 제한. 생략된 후보는 승인된 연결이 아님.
        if len(matches)>15:
            continue
        for in_heading,sec in sorted(matches,key=lambda x:(-x[0],x[1]["section_id"]))[:8]:
            candidates.append({"policy_id":p["policy_id"],"policy_title":title,
                "pdf_section_id":sec["section_id"],"pdf_source":sec["source"],
                "page_start":sec["page_start"],"page_end":sec["page_end"],
                "match_method":"exact_title_in_heading" if in_heading else "exact_title_in_body",
                "review_status":"pending","approved":False,
                "review_action":"동일 정책/기준연도/대상/시행기간 여부를 공식 문서와 대조"})
    return candidates


def build_cross_pdf_duplicate_candidates(pdf_sections):
    """5번째 분권이 있을 때 종합본의 정확히 중복되는 긴 문자열을 검수 후보로 반환."""
    fifth=[s for s in pdf_sections if "분권_raw_pages" in clean_text(s.get("source"))]
    general=[s for s in pdf_sections if s.get("source")=="2026_나에게_힘이_되는_복지서비스"]
    if not fifth or not general:return []
    def normalize(s):return re.sub(r"[^0-9a-zA-Z가-힣]", "", clean_text(s))
    candidate=[]
    for a in fifth:
        n=normalize(a.get("content"))
        if len(n)<160:continue
        # 의미 유사도가 아니라 긴 정확한 문자열의 중복 후보. 검수하지 않고 병합하면 안 됨.
        anchors=[n[x:x+60] for x in (min(50,len(n)//5),len(n)//2, max(0,len(n)-100)) if len(n[x:x+60])==60]
        for b in general:
            o=normalize(b.get("content"))
            matches=sum(x in o for x in anchors)
            if matches>=2:
                candidate.append({"elderly_section_id":a["section_id"],"general_section_id":b["section_id"],
                    "matching_anchors":matches,"review_status":"pending","index_deduplicate_approved":False})
    return candidate

def validate_chunks(policy_chunks, pdf_chunks, facility_chunks, policies, pdf_sections, facilities, tokenizer_name="", max_tokens=512):
    all_chunks = policy_chunks + pdf_chunks + facility_chunks
    if not all_chunks:
        raise ValueError("청크가 생성되지 않았습니다.")
    for key in ("id", "chunk_id"):
        dups = [k for k, n in Counter(x[key] for x in all_chunks).items() if n > 1]
        if dups:
            raise ValueError(f"청크 {key} 중복: {dups[:5]}")
    limits = {"policy": POLICY_MAX_BODY_CHARS, "guideline": PDF_MAX_BODY_CHARS, "facility": POLICY_MAX_BODY_CHARS}
    for c in all_chunks:
        if not c["text"].strip() or not 0 < len(c["body_text"]) <= limits[c["record_type"]]:
            raise ValueError(f"본문 길이 이상: {c['chunk_id']}")
        if not c["metadata"] or any(type(v) not in (str, int, float, bool) for v in c["metadata"].values()):
            raise TypeError(f"메타데이터 형식 오류: {c['chunk_id']}")
        uuid.UUID(c["id"])
    for source_ids, chunk_ids, what in [
        ({p["policy_id"] for p in policies}, {c["policy_id"] for c in policy_chunks}, "정책"),
        ({f["facility_id"] for f in facilities}, {c["facility_id"] for c in facility_chunks}, "시설"),
        ({s["section_id"] for s in pdf_sections if clean_text(s.get("content"))}, {c["section_id"] for c in pdf_chunks}, "본문 있는 PDF")]:
        missing = source_ids - chunk_ids
        if missing:
            raise ValueError(f"{what} 청킹 누락: {sorted(missing)[:5]}")
    status = "not_checked_model_not_selected"
    if tokenizer_name.strip():
        try:
            from transformers import AutoTokenizer
        except ImportError as e:
            raise ImportError("토큰 검증에는 pip install transformers가 필요합니다.") from e
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_name, use_fast=True)
        oversized = []
        for c in all_chunks:
            n = len(tokenizer.encode(c["text"], add_special_tokens=True))
            c["model_token_count"] = n
            if n > max_tokens:
                oversized.append((c["chunk_id"], n))
        if oversized:
            raise ValueError(f"토큰 한도 {max_tokens} 초과: {len(oversized)}건, 샘플 {oversized[:3]}")
        status = f"checked_with:{tokenizer_name} max={max_tokens}"
    return all_chunks, status


def build_graph_export(policies, pdf_sections, facilities, registry, all_chunks, embedding_ready):
    nodes, relations = [], []
    def node(label, key, props):
        nodes.append({"label": label, "id": key, "properties": props})
    def link(typ, fl, fi, tl, ti):
        relations.append({"type": typ, "from_label": fl, "from_id": fi, "to_label": tl, "to_id": ti})
    for p in policies:
        node("Policy", p["policy_id"], {"policy_id": p["policy_id"], "title": clean_text(p.get("title")),
            "source_type": clean_text(p.get("source_type")), "detail_fetched": p.get("detail_fetched") is True,
            "region_scope": clean_text(p.get("region_scope")) or "unknown",
            "sido_name": clean_text(p.get("sido_name")), "sigungu_name": clean_text(p.get("sigungu_name"))})
    for f in facilities:
        node("Facility", f["facility_id"], {"facility_id": f["facility_id"],
            "title": f["title"], "region": clean_text(f.get("region")),
            "address_road": clean_text(f.get("address_road")),
            "latitude": f.get("latitude"), "longitude": f.get("longitude")})
    docs = {r["source"]: r["document_id"] for r in registry}
    for d in registry:
        node("PdfDocument", d["document_id"], {"document_id": d["document_id"],
            "source": d["source"], "file_name_candidate": d["file_name_candidate"] or "",
            "review_status": "pending"})
    for s in pdf_sections:
        sid = s["section_id"]
        doc_id = docs[clean_text(s["source"])]
        heading = " > ".join(clean_text(s.get(k)) for k in ("title", "section", "subsection") if clean_text(s.get(k)))
        node("PdfSection", sid, {"section_id": sid, "document_id": doc_id,
            "section_title": heading, "page_start": s["page_start"], "page_end": s["page_end"]})
        link("HAS_SECTION", "PdfDocument", doc_id, "PdfSection", sid)
    for c in all_chunks:
        node("Chunk", c["id"], {"chunk_id": c["chunk_id"], "record_type": c["record_type"],
            "qdrant_point_id": c["id"], "include_in_embedding": c["metadata"].get("include_in_embedding", True)})
        if c["record_type"] == "policy":
            link("HAS_CHUNK", "Policy", c["policy_id"], "Chunk", c["id"])
        elif c["record_type"] == "guideline":
            link("HAS_CHUNK", "PdfSection", c["section_id"], "Chunk", c["id"])
        else:
            link("HAS_CHUNK", "Facility", c["facility_id"], "Chunk", c["id"])
    keys = [(r["label"], r["id"]) for r in nodes]
    if len(keys) != len(set(keys)):
        raise ValueError("Neo4j 노드 키 중복")
    known = set(keys)
    edge_keys = set()
    for e in relations:
        if (e["from_label"], e["from_id"]) not in known or (e["to_label"], e["to_id"]) not in known:
            raise ValueError(f"Neo4j 고아 관계: {e}")
        key = (e["type"], e["from_label"], e["from_id"], e["to_label"], e["to_id"])
        if key in edge_keys:
            raise ValueError(f"Neo4j 중복 관계: {key}")
        edge_keys.add(key)
    qdrant = {c["id"] for c in embedding_ready}
    if not qdrant.issubset({n["id"] for n in nodes if n["label"] == "Chunk"}):
        raise ValueError("Qdrant 포인트 ID가 Neo4j Chunk에 존재하지 않습니다.")
    return nodes, relations


def save_jsonl_atomic(path: Path, rows: list[dict]):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")
    tmp.replace(path)


def save_json_atomic(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_pipeline(config: Config) -> dict:
    root = Path(config.input_dir).expanduser().resolve()
    files = find_inputs(root)
    output = Path(config.output_dir).expanduser().resolve() if config.output_dir else root / "splitting_output"
    if output == root:
        raise ValueError("출력 폴더를 입력 폴더와 동일하게 지정하지 마세요.")
    if any(output == p or (p and output in p.parents) for p in files.values()):
        raise ValueError("출력 폴더가 입력 파일의 상위 경로입니다. 별도 폴더를 지정하세요.")
    if not (50 <= OVERLAP_CHARS < min(POLICY_MAX_BODY_CHARS, PDF_MAX_BODY_CHARS) // 3):
        raise ValueError("청크 오버랩이 최대 길이의 1/3 이상입니다.")
    warnings: list[str] = []
    central = read_jsonl(files["central"])
    local = read_jsonl(files["local"])
    facilities_raw = read_json_array(files["facility"])
    pdf_base = read_jsonl(files["pdf_sections"])
    for kind, rows in [("central", central), ("local", local), ("facility", facilities_raw), ("pdf_sections", pdf_base)]:
        check_count(kind, len(rows), config.strict_counts, warnings)
    check_unique(central, "policy_id", "중앙부처 정책")
    if any(clean_text(p.get("source_type")) != "central_welfare_api" for p in central):
        raise ValueError("중앙부처 정책 파일이 아닙니다. feature/pre-splitting-ready의 policies.jsonl을 넣으세요.")
    policy_rows = central + normalize_local(local)
    facility_rows = normalize_facilities(facilities_raw)
    check_unique(policy_rows, "policy_id", "통합 정책")
    pdf_sections = list(pdf_base)
    elderly_mode = "missing"
    if files["elderly_sections"]:
        extra = read_jsonl(files["elderly_sections"])
        pdf_sections.extend(extra)
        elderly_mode = "preprocessed_jsonl"
        if files["elderly_pdf_raw"]:
            warnings.append("노령층 분권 JSONL과 원본 PDF가 모두 있어 중복 청킹 방지를 위해 JSONL만 처리했습니다.")
    elif files["elderly_pdf_raw"]:
        extra = extract_elderly_pdf_pages(files["elderly_pdf_raw"])
        pdf_sections.extend(extra)
        elderly_mode = "raw_pdf_page_fallback"
        warnings.append("5번째 PDF는 페이지별 임시 추출입니다. 표, 문단 순서, 사업별 의미 경계를 원본과 대조해야 합니다.")
    else:
        msg = "5번째 PDF(노령층 분권) 원본/전처리 파일이 없어 4종 PDF 섹션만 처리합니다."
        if config.require_fifth_pdf:
            raise FileNotFoundError(msg + " feature/10-api-data-processing 브랜치의 노령층 분권 PDF를 입력 폴더에 넣으세요.")
        warnings.append(msg)
    validate_pdf_sections(pdf_sections)
    pdf_sources = Counter(s["source"] for s in pdf_sections)
    if len(pdf_sources) < (5 if elderly_mode != "missing" else 4):
        warnings.append(f"PDF source 키 {len(pdf_sources)}개; 예상된 4/5종과 파일명·출처를 점검하세요.")
    print("[1/5] 원본 검사 완료:")
    print(f"       중앙 {len(central):,} / 지자체 {len(local):,} / 시설 {len(facility_rows):,} / PDF 섹션 {len(pdf_sections):,}")
    print(f"       지자체 상세 미확보 {sum(p['detail_fetched'] is False for p in policy_rows if p['source_type']=='local_welfare_api'):,}건")
    print(f"       PDF 분권 처리: {elderly_mode} / PDF 구분 {len(pdf_sources)}종")
    link_candidates=build_policy_pdf_link_candidates(policy_rows,pdf_sections)
    duplicate_candidates=build_cross_pdf_duplicate_candidates(pdf_sections)
    policy_chunks = build_policy_chunks(policy_rows)
    pdf_chunks, review_queue, registry = build_pdf_chunks(pdf_sections, exclude_toc=config.exclude_clear_toc,
        elderly_pdf_path=files["elderly_pdf_raw"] if elderly_mode=="raw_pdf_page_fallback" else None)
    facility_chunks = build_facility_chunks(facility_rows)
    raw_pdf_paths = find_original_pdf_paths(files)
    page_alignment = align_source_pages(pdf_chunks, raw_pdf_paths, pdf_sections)
    for reg in registry:
        path = raw_pdf_paths.get(reg["source"])
        if path and reg["source"] != "2026_나에게_힘이_되는_복지서비스_노령층_분권_raw_pages":
            reg["file_name"] = path.name
            reg["file_name_verified"] = True
            reg["source_file_hash"] = sha256_file(path)
            reg["source_file_hash_verified"] = False  # PDF 추출 레이아웃/페이지별 대조 검수 필요
    print("[2/5] 분할 완료:", f"정책 {len(policy_chunks):,} / PDF {len(pdf_chunks):,} / 시설 {len(facility_chunks):,} 청크")
    all_chunks, token_status = validate_chunks(policy_chunks, pdf_chunks, facility_chunks,
        policy_rows, pdf_sections, facility_rows, config.tokenizer_name, config.max_embedding_tokens)
    # 사용자 응답에서 지역·수급조건을 단정하지 않도록 검수 상태를 필터로 전달.
    embedding_ready = [{"id": c["id"], "text": c["text"], "metadata": c["metadata"]}
                       for c in all_chunks if c["metadata"].get("include_in_embedding", True)]
    nodes, relations = build_graph_export(policy_rows, pdf_sections, facility_rows, registry, all_chunks, embedding_ready)
    print("[3/5] 검증 완료:", f"Neo4j 노드 {len(nodes):,} / 관계 {len(relations):,} / Qdrant 후보 {len(embedding_ready):,}")
    # API 키/사용자 개인 경로를 포함하지 않고 로컬 파일 해시와 논리적인 출처만 기록.
    input_inventory = {}
    for kind, file in files.items():
        if file:
            input_inventory[kind] = {"name": file.name, "sha256": sha256_file(file),
                                     "size_bytes": file.stat().st_size,
                                     "repository_branch": SOURCE_BRANCHES.get(kind, "external_preprocessed"),
                                     "branch_head_observed": OBSERVED_HEADS.get(kind)}
    manifest = {
        "schema_version": SCHEMA_VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
        "github_repository": REPO, "input_inventory": input_inventory,
        "sources_by_pdf": dict(sorted(pdf_sources.items())), "elderly_pdf_mode": elderly_mode,
        "storage_targets": {"vector_search": "Qdrant", "relationships": "Neo4j",
                            "db_write_performed": False, "join_key": "Qdrant.point.id = Neo4j.Chunk.id"},
        "parameters": {"policy_max_body_chars": POLICY_MAX_BODY_CHARS,
                       "pdf_max_body_chars": PDF_MAX_BODY_CHARS, "facility_max_body_chars": POLICY_MAX_BODY_CHARS,
                       "overlap_chars": OVERLAP_CHARS,
                       "boundary_priority": "paragraph > newline > sentence/space > hard-limit",
                       "tokenizer_status": token_status},
        "source_records": {"central_policies": len(central), "local_policies": len(local),
                           "total_policies": len(policy_rows), "local_detail_missing": sum(not p["detail_fetched"] for p in policy_rows if p["source_type"]=="local_welfare_api"),
                           "facilities": len(facility_rows), "pdf_sections": len(pdf_sections), "pdf_documents": len(pdf_sources)},
        "generated": {"policy_chunks": len(policy_chunks), "guideline_chunks": len(pdf_chunks),
                      "facility_chunks": len(facility_chunks), "total_chunks": len(all_chunks),
                      "embedding_ready": len(embedding_ready), "neo4j_nodes": len(nodes),
                      "neo4j_relationships": len(relations)},
        "page_alignment": page_alignment,
        "candidate_review_counts":{"policy_pdf_link_candidates":len(link_candidates),
                                   "fifth_pdf_duplicate_candidates":len(duplicate_candidates)},
        "warnings": warnings + ["지역/자격/금액의 공식 검증 없음", "정책-PDF 자동 연결 승인 없음",
                                "모델 미지정 시 토큰 제한 적합성 미확인", "DB 실제 적재·임베딩 미실행"],
    }
    quality = {
        "status": "structural_validation_passed_semantic_review_pending",
        "source_counts": manifest["source_records"], "source_pdf_categories": manifest["sources_by_pdf"],
        "target_databases": ["Qdrant", "Neo4j"], "elderly_pdf_mode": elderly_mode,
        "policy_chunk_count": len(policy_chunks), "pdf_chunk_count": len(pdf_chunks),
        "facility_chunk_count": len(facility_chunks), "total_chunk_count": len(all_chunks),
        "embedding_candidate_count": len(embedding_ready),
        "neo4j_nodes": len(nodes), "neo4j_relationships": len(relations),
        "pending_region_policy_count": sum(p.get("region_validation_status")!="approved" for p in policy_rows),
        "local_list_only_policy_count": sum(not p["detail_fetched"] for p in policy_rows if p["source_type"]=="local_welfare_api"),
        "pdf_sections_with_review_flags": len(review_queue),
        "empty_pdf_sections": sum(not clean_text(p.get("content")) for p in pdf_sections),
        "max_text_chars": max(map(lambda c:len(c["text"]), all_chunks)),
        "max_body_chars": max(map(lambda c:len(c["body_text"]), all_chunks)),
        "duplicate_chunk_ids": 0, "duplicate_point_ids": 0,
        "tokenizer_status": token_status, "page_alignment": page_alignment,
        "policy_pdf_link_candidates":len(link_candidates),
        "fifth_pdf_duplicate_candidates":len(duplicate_candidates),
        "pdf_table_chunk_count":sum(c["metadata"].get("content_kind")=="markdown_table_row" for c in pdf_chunks),
        "pdf_table_rows_referenced":len({(c["section_id"],c.get("table_row_sha256")) for c in pdf_chunks if "table_row_sha256" in c}),
        "pdf_multi_page_chunk_count":sum(c["metadata"]["page_start"]!=c["metadata"]["page_end"] for c in pdf_chunks),
        "pre_embedding_readiness":"TECHNICALLY_PREPARED_WITH_MANUAL_AND_SOURCE_BLOCKERS",
        "limitations":{"fifth_pdf_missing":elderly_mode=="missing","local_detail_unavailable":sum(not p["detail_fetched"] for p in policy_rows if p["source_type"]=="local_welfare_api"),
         "region_policy_approvals":sum(p.get("region_validation_status")=="approved" for p in policy_rows),
         "tokenizer_verified":bool(config.tokenizer_name.strip()),
         "pdf_page_specific_citations_approved":False,
         "policy_pdf_links_approved":False},
        "warnings": manifest["warnings"],
    }
    # 원본 입력 파일 미변경; 출력 파일만 지정된 새 폴더에 저장
    output.mkdir(parents=True, exist_ok=True)
    outputs = [
        ("normalized_policies.jsonl", policy_rows),
        ("normalized_facilities.jsonl", facility_rows),
        ("normalized_guideline_sections.jsonl", pdf_sections),
        ("policy_chunks.jsonl", policy_chunks),
        ("guideline_chunks.jsonl", pdf_chunks),
        ("facility_chunks.jsonl", facility_chunks),
        ("embedding_ready.jsonl", embedding_ready),
        ("neo4j_nodes.jsonl", nodes),
        ("neo4j_relationships.jsonl", relations),
        ("document_registry.jsonl", registry),
        ("policy_pdf_link_candidates.jsonl", link_candidates),
        ("cross_pdf_duplicate_candidates.jsonl", duplicate_candidates),
    ]
    for filename, rows in outputs:
        save_jsonl_atomic(output / filename, rows)
    with (output / "pdf_review_queue.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["record_type", "source_id", "source", "page_start", "page_end", "flags", "table_chunk_count"])
        writer.writeheader(); writer.writerows(review_queue)
    # 판정 불가능한 검수 사안은 전체 목록을 남기되 '승인'으로 위장하지 않는다.
    with (output/"policy_region_review.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["policy_id","title","source_type","sido_hint","sigungu_hint","region_scope","region_validation_status","eligible_for_region_filter","review_action"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for p in policy_rows:
            w.writerow(dict(policy_id=p["policy_id"],title=p["title"],source_type=p["source_type"],
                            sido_hint=p.get("sido_name") or "",sigungu_hint=p.get("sigungu_name") or "",
                            region_scope=p.get("region_scope") or "unknown",region_validation_status=p.get("region_validation_status") or "pending",
                            eligible_for_region_filter=p.get("region_validation_status")=="approved",
                            review_action="공식 정책 원문에서 지역 적용 범위 수동 확인"))
    with (output/"local_detail_missing_review.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["policy_id","source_serv_id","title","sido_name","sigungu_name","source_url","detail_fetched","review_action"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for p in policy_rows:
            if p["source_type"]=="local_welfare_api" and not p["detail_fetched"]:
                w.writerow({k:("공식 API 재수집 또는 원문 수동 검수" if k=="review_action" else p.get(k,"")) for k in fields})
    with (output/"pdf_financial_review.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["section_id","source","page_start","page_end","has_markdown_table","financial_keyword_excerpt","priority","review_action"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for sec in pdf_sections:
            content=clean_text(sec.get("content"))
            mat=FINANCIAL_PATTERN.search(content)
            if mat:
                ex=content[max(0,mat.start()-70):min(len(content),mat.end()+105)].replace("\n"," ")
                istable=bool(re.search(r"(?m)^\s*\|.+\|\s*$",content))
                w.writerow({"section_id":sec["section_id"],"source":sec["source"],"page_start":sec["page_start"],
                            "page_end":sec["page_end"],"has_markdown_table":istable,
                            "financial_keyword_excerpt":ex,"priority":"P0" if istable else "P1",
                            "review_action":"공식 PDF 원문에서 수치/연도/단위/예외 확인"})
    with (output/"citation_page_review.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["chunk_id","source","section_id","page_start","page_end","page_alignment_status","candidate_page","review_action"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for c in pdf_chunks:
            m=c["metadata"]
            if m["page_alignment_status"] not in ("single_page_section_not_original_verified",):
                w.writerow({"chunk_id":c["chunk_id"],"source":m["source"],"section_id":c["section_id"],
                            "page_start":m["page_start"],"page_end":m["page_end"],
                            "page_alignment_status":m["page_alignment_status"],
                            "candidate_page":m.get("citation_page_candidate", ""),
                            "review_action":"원본 PDF 대조 전 특정 페이지로 인용 금지"})
    save_json_atomic(output / "split_quality_report.json", quality)
    save_json_atomic(output / "index_manifest.json", manifest)
    print("[4/5] 결과 저장 완료:", output)
    print("[5/5] 입력 파일 원본 보존 / 외부 API 호출·DB 쓰기 없음")
    for filename, _ in outputs:
        print("  -", filename)
    print("  - pdf_review_queue.csv / pdf_financial_review.csv / citation_page_review.csv")
    print("  - policy_region_review.csv / local_detail_missing_review.csv / split_quality_report.json / index_manifest.json")
    for w in warnings:
        print("[검토 필요]", w)
    return manifest


def main():
    p = argparse.ArgumentParser(description="SKN36 다중 소스 자동 Splitting - Qdrant + Neo4j")
    p.add_argument("--input-dir", type=Path, required=True, help="다운로드한 입력 파일 4~5개가 있는 폴더")
    p.add_argument("--output-dir", type=Path, default=None, help="출력 경로 (생략하면 입력 폴더/splitting_output)")
    p.add_argument("--require-fifth-pdf", action="store_true", help="5번째 노령층 분권 PDF까지 요구")
    p.add_argument("--strict-counts", action="store_true", help="조사 시점의 데이터 건수와 다르면 중단")
    p.add_argument("--tokenizer-name", default="", help="선택: HF tokenizer 이름/로컬 폴더")
    p.add_argument("--max-embedding-tokens", type=int, default=512)
    args = p.parse_args()
    run_pipeline(Config(args.input_dir, args.output_dir, args.require_fifth_pdf,
                        args.strict_counts, args.tokenizer_name, args.max_embedding_tokens))


if __name__ == "__main__":
    main()
