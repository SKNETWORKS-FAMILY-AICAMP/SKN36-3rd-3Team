"""STEP 3-B: Keep explicitly sourced regions; quarantine conflicts and unknowns.
자동 후보는 검증된 신청 지역이 아님. 수동 confirmed_region이 있으면 우선 적용.
"""
import csv
from pathlib import Path
from .io_utils import read_jsonl,write_jsonl,ensure_unique,new_run_dir

FORMER_JEONNAM = {
    '목포시','여수시','순천시','나주시','광양시','담양군','곡성군','구례군',
    '고흥군','보성군','화순군','장흥군','강진군','해남군','영암군',
    '무안군','함평군','영광군','장성군','완도군','진도군','신안군'
}

FORMER_GWANGJU = {'동구','서구','남구','북구','광산구'}

ALIASES = {
    '서울':'seoul','서울시':'seoul','서울특별시':'seoul','seoul':'seoul',
    '경기':'gyeonggi','경기도':'gyeonggi','gyeonggi':'gyeonggi',
    '부산광역시':'busan','busan':'busan',
    '대구광역시':'daegu','daegu':'daegu',
    '인천광역시':'incheon','incheon':'incheon',
    '대전광역시':'daejeon','daejeon':'daejeon',
    '울산광역시':'ulsan','ulsan':'ulsan',
    '세종특별자치시':'sejong','sejong':'sejong',
    '강원특별자치도':'gangwon','gangwon':'gangwon',
    '충청북도':'chungbuk','chungbuk':'chungbuk',
    '충청남도':'chungnam','chungnam':'chungnam',
    '전북특별자치도':'jeonbuk','전라북도':'jeonbuk','jeonbuk':'jeonbuk',
    '경상북도':'gyeongbuk','gyeongbuk':'gyeongbuk',
    '경상남도':'gyeongnam','gyeongnam':'gyeongnam',
    '제주특별자치도':'jeju','jeju':'jeju',
    '전남':'jeonnam','전라남도':'jeonnam','jeonnam':'jeonnam',
    '광주':'gwangju','광주광역시':'gwangju','gwangju':'gwangju',
    '전국':'national','전국공통':'national','전국 공통':'national','national':'national',
    '판단불가':'unknown','판단 불가':'unknown','미확정':'unknown','unknown':'unknown',
}
INCLUDED_REGIONS = set(ALIASES.values()) - {'unknown'}

def as_value(x):
    if x is None: return None
    v = str(x).strip()
    return None if not v or v.lower() in {'none','null','nan','<na>'} else v

def candidate_label(x):
    raw = as_value(x)
    if raw is None: return None
    val = ALIASES.get(raw.lower(), ALIASES.get(raw))
    if not val: raise ValueError(f'지원하지 않는 지역 분류 값: {x!r}')
    return val

def classify_region(p, candidate_by_id, include_unreviewed_candidates=True):
    pid = str(p['policy_id']).strip()
    requested = as_value(p.get('requested_region'))
    sido = as_value(p.get('sido_name'))
    raw_sido = as_value(p.get('raw_sido_name'))
    sigungu = as_value(p.get('sigungu_name'))
    legacy = as_value(p.get('legacy_area_group'))
    reasons = p.get('region_review_reasons') or []
    if isinstance(reasons, str): reasons = [reasons]
    conflicting = any('conflict' in str(r) for r in reasons)

    cand = candidate_by_id.get(pid)
    if cand is not None:
        confirmed = candidate_label(cand.get('confirmed_region'))
        auto = candidate_label(cand.get('candidate_region'))
        if confirmed:
            label, origin, verified = confirmed, 'manual_confirmed', True
        elif sido=='광주광역시' or raw_sido=='광주광역시':
            label, origin, verified = 'gwangju', 'explicit_gwangju_sido', False
        elif include_unreviewed_candidates:
            label, origin, verified = auto, 'automatic_candidate_unverified', False
        else:
            label, origin, verified = 'unknown', 'awaiting_manual_review', False
    else:
        if conflicting:
            label, origin, verified = 'unknown', 'region_conflict', False
        elif requested and requested != '전남광주통합특별시' and candidate_label_or_none(requested):
            label, origin, verified = candidate_label(requested), 'original_requested_region', False
        elif requested == '전남광주통합특별시':
            if sido=='광주광역시' or raw_sido=='광주광역시' or legacy=='former_gwangju' or sigungu in FORMER_GWANGJU:
                label, origin, verified = 'gwangju','original_region_metadata',False
            elif legacy=='former_jeonnam' or sigungu in FORMER_JEONNAM:
                label, origin, verified = 'jeonnam','original_sigungu_metadata',False
            else:
                label, origin, verified = 'unknown','unclassified_combined_region',False
        elif sido and sido != '전남광주통합특별시' and candidate_label_or_none(sido):
            label, origin, verified = candidate_label(sido), 'original_sido_metadata', False
        else:
            label, origin, verified = 'unknown','unexpected_original_region',False

    # 수동 확정을 제외하고 원본 충돌이 있으면 안전하게 보류
    if conflicting and origin != 'manual_confirmed':
        label, origin, verified = 'unknown', 'region_conflict', False
    status = 'included' if label in INCLUDED_REGIONS else 'excluded_unknown'
    return {
        **p,
        'region_selection_status': status,
        'region_selection_label': label,
        'region_selection_source': origin,
        'region_selection_verified': verified,
        'region_selection_note': as_value(cand.get('review_note')) if cand else None,
        'region_selection_evidence': as_value(cand.get('evidence_text')) if cand else None,
    }

def load_candidates(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    ids=[r.get('policy_id','').strip() for r in rows]
    if len(ids)!=len(set(ids)) or not all(ids):raise ValueError('후보 CSV ID 중복/누락')
    return dict(zip(ids,rows))

def candidate_label_or_none(raw):
    try:
        return candidate_label(raw)
    except ValueError:
        return None

def run(input_path,candidate_csv,output_base,include_unreviewed_candidates=True):
    policies=read_jsonl(input_path);ensure_unique(policies)
    candidate_by_id=load_candidates(candidate_csv)
    by_id={p['policy_id']:p for p in policies}
    expected={p['policy_id'] for p in policies if (p.get('requested_region')=='전남광주통합특별시' or p.get('sido_name')=='전남광주통합특별시') and p.get('legacy_area_group')=='unknown'}
    if expected!=set(candidate_by_id):raise ValueError(f'후보 CSV 정책 ID 불일치. 누락={len(expected-set(candidate_by_id))}, 불필요={len(set(candidate_by_id)-expected)}')
    classified=[classify_region(p,candidate_by_id,include_unreviewed_candidates) for p in policies]
    included=[p for p in classified if p['region_selection_status']=='included']
    gwangju=[]  # Retained for historical output compatibility; explicit Gwangju is included.
    unknown=[p for p in classified if p['region_selection_status']=='excluded_unknown']
    assert len(included)+len(gwangju)+len(unknown)==len(policies)
    output=new_run_dir(output_base)
    for name,data in [('policies_selected.jsonl',included),('policies_gwangju_excluded.jsonl',gwangju),('policies_unknown_excluded.jsonl',unknown),('policies_all_with_selection.jsonl',classified)]:write_jsonl(output/name,data)
    review_cols=['policy_id','title','region_selection_status','region_selection_label','region_selection_source','region_selection_verified','region_selection_evidence']
    review=[{k:p.get(k) for k in review_cols} for p in classified if p['region_selection_source'] in {'automatic_candidate_unverified','region_conflict','unclassified_combined_region'}]
    with (output/'region_selection_review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=review_cols);w.writeheader();w.writerows(review)
    return {'selected':len(included),'gwangju':len(gwangju),'unknown':len(unknown),'run_dir':str(output)}
