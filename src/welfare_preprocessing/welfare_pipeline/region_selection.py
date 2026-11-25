"""Nationwide classification: preserve every record; separate search eligibility review."""
import csv
from pathlib import Path
from .io_utils import read_jsonl, write_jsonl, ensure_unique, new_run_dir
from .normalize_policies import FORMER_JEONNAM, FORMER_GWANGJU

PROVINCES = {
    '서울특별시':'seoul', '경기도':'gyeonggi', '부산광역시':'busan',
    '대구광역시':'daegu', '인천광역시':'incheon', '대전광역시':'daejeon',
    '울산광역시':'ulsan', '세종특별자치시':'sejong', '강원특별자치도':'gangwon',
    '충청북도':'chungbuk', '충청남도':'chungnam', '전북특별자치도':'jeonbuk',
    '경상북도':'gyeongbuk', '경상남도':'gyeongnam', '제주특별자치도':'jeju',
    '광주광역시':'gwangju', '전라남도':'jeonnam', '전남광주통합특별시':'gwangju_jeonnam',
}
ALIASES = {**PROVINCES, **{v:v for v in PROVINCES.values()},
    '전남':'jeonnam', '광주':'gwangju', '서울':'seoul', '경기':'gyeonggi',
    '전국':'national', '전국공통':'national', '전국 공통':'national', 'national':'national',
    '판단불가':'unknown', '판단 불가':'unknown', '미확정':'unknown', 'unknown':'unknown'}

def as_value(x):
    if x is None: return None
    s = str(x).strip()
    return None if not s or s.lower() in {'none','null','nan','<na>'} else s

def candidate_label(x):
    s = as_value(x)
    if s is None: return None
    label = ALIASES.get(s, ALIASES.get(s.lower()))
    if label is None: raise ValueError(f'지원하지 않는 지역 분류 값: {x!r}')
    return label

def classify_region(p, candidate_by_id, include_unreviewed_candidates=True):
    pid = str(p['policy_id']).strip()
    cand = candidate_by_id.get(pid) or {}
    confirmed = candidate_label(cand.get('confirmed_region'))
    auto = candidate_label(cand.get('candidate_region'))
    sido = as_value(p.get('sido_name'))
    requested = as_value(p.get('requested_region'))
    district = as_value(p.get('sigungu_name'))
    legacy = as_value(p.get('legacy_area_group'))
    reasons = p.get('region_review_reasons') or []
    if isinstance(reasons, str): reasons = [reasons]
    conflict = any('conflict' in str(r) for r in reasons)
    verified = False
    if confirmed:
        label, source, verified = confirmed, 'manual_confirmed', confirmed != 'unknown'
    elif conflict:
        label, source = 'unknown', 'region_conflict'
    elif sido == '전남광주통합특별시' or requested == '전남광주통합특별시':
        if legacy == 'former_jeonnam' or district in FORMER_JEONNAM:
            label, source = 'jeonnam', 'original_sigungu_metadata'
        elif legacy == 'former_gwangju' or district in FORMER_GWANGJU:
            label, source = 'gwangju', 'original_sigungu_metadata'
        elif auto and include_unreviewed_candidates:
            label, source = auto, 'automatic_candidate_unverified'
        else:
            label, source = 'unknown', 'unclassified_combined_region'
    else:
        label = PROVINCES.get(sido or requested, 'unknown')
        source = 'original_region_metadata' if label != 'unknown' else 'unexpected_original_region'
    scope_verified = p.get('region_scope_verified') is True
    # A known administrative label is not proof of eligibility. An unverified
    # national candidate must never be treated as a nationwide entitlement.
    needs_review = (label in {'unknown','gwangju_jeonnam'} or
                    source == 'automatic_candidate_unverified' or
                    (conflict and not verified) or
                    (not district and not (label == 'national' and verified)))
    search_status = ('review_required' if needs_review else
                     'scope_verified' if scope_verified else 'region_candidate')
    return {**p,
        'region_selection_status': 'included',  # retained, not eligibility approval
        'region_selection_label': label,
        'region_selection_source': source,
        'region_selection_verified': verified,
        'region_search_status': search_status,
        'region_selection_note': as_value(cand.get('review_note')),
        'region_selection_evidence': as_value(cand.get('evidence_text'))}

def load_candidates(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    ids = [r.get('policy_id','').strip() for r in rows]
    if len(ids) != len(set(ids)) or not all(ids): raise ValueError('후보 CSV ID 중복/누락')
    return dict(zip(ids, rows))

def run(input_path, candidate_csv, output_base, include_unreviewed_candidates=True):
    policies = read_jsonl(input_path); ensure_unique(policies)
    candidate_by_id = load_candidates(candidate_csv)
    known = {str(p['policy_id']).strip() for p in policies}
    if set(candidate_by_id) - known: raise ValueError('현재 입력에 없는 후보 CSV ID 존재')
    classified = [classify_region(p, candidate_by_id, include_unreviewed_candidates) for p in policies]
    ensure_unique(classified)
    if len(classified) != len(policies): raise ValueError('지역 분류 과정에서 레코드 손실')
    review = [p for p in classified if p['region_search_status'] != 'scope_verified']
    output = new_run_dir(output_base)
    for name, rows in [('policies_selected.jsonl', classified),
                       ('policies_all_with_selection.jsonl', classified),
                       ('policies_region_review.jsonl', review)]:
        write_jsonl(output/name, rows)
    cols = ['policy_id','title','sido_name','sigungu_name','region_selection_status',
            'region_selection_label','region_selection_source','region_selection_verified',
            'region_search_status','region_selection_evidence']
    with (output/'region_selection_review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        w.writerows({k:p.get(k) for k in cols} for p in review)
    return {'selected':len(classified),'review':len(review),
            'gwangju':sum(p['region_selection_label']=='gwangju' for p in classified),
            'unknown':sum(p['region_selection_label']=='unknown' for p in classified),
            'run_dir':str(output)}
