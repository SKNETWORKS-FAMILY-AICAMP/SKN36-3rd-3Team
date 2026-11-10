"""STEP 2: 목록·상세 필드 결합, 날짜/태그 정제, 지역 메타데이터 생성.
원본 JSONL 1행에 목록 및 detail_ 필드가 함께 존재하는 구조를 전제로 함.
"""
import json,re
from datetime import datetime
from .io_utils import read_jsonl,write_jsonl,ensure_unique

def value_or_none(v):
    if v is None: return None
    if isinstance(v,str):
        s=v.strip()
        return None if s.lower() in ('','nan','none','null','<na>') else s
    return v

FIELD_MAPPING = {
    'title': ('detail_servNm', 'servNm'),
    'summary': ('detail_servDgst', 'servDgst'),
    'target_text': ('detail_sprtTrgtCn', 'sprtTrgtCn'),
    'selection_criteria_text': ('detail_slctCritCn', 'slctCritCn'),
    'benefit_text': ('detail_alwServCn', 'alwServCn'),
    'application_text': ('detail_aplyMtdCn', 'aplyMtdCn'),
    'application_method_name': ('detail_aplyMtdNm', 'aplyMtdNm'),
    'department': ('detail_bizChrDeptNm', 'bizChrDeptNm'),
    'contact': ('detail_inqNum', 'inqNum'),
    'start_date_raw': ('detail_enfcBgngYmd', 'enfcBgngYmd'),
    'end_date_raw': ('detail_enfcEndYmd', 'enfcEndYmd'),
    'updated_at_source_raw': ('detail_lastModYmd', 'lastModYmd'),
    'life_stage_tags': ('detail_lifeNmArray', 'lifeNmArray'),
    'target_group_tags': ('detail_trgterIndvdlNmArray', 'trgterIndvdlNmArray'),
    'interest_tags': ('detail_intrsThemaNmArray', 'intrsThemaNmArray'),
    'support_cycle': ('detail_sprtCycNm', 'sprtCycNm'),
    'provider_type': ('detail_srvPvsnNm', 'srvPvsnNm'),
}

def choose_field(row, candidates):
    for col in candidates:
        val = value_or_none(row.get(col))
        if val is not None:
            return val, col
    return None, None

def as_text(v):
    if v is None:
        return None
    return str(v).strip() or None
def parse_date(raw):
    raw = as_text(raw)
    if raw is None: return None
    digits = raw.replace('-', '')
    if not re.fullmatch(r'\d{8}', digits): return None
    try:
        return datetime.strptime(digits, '%Y%m%d').date().isoformat()
    except ValueError:
        return None

def parse_tags(raw):
    if raw is None: return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if x is not None and str(x).strip()]
    s = as_text(raw)
    if not s: return []
    if s.startswith('[') and s.endswith(']'):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list): return parse_tags(parsed)
        except json.JSONDecodeError:
            pass
    return [x.strip() for x in s.split(',') if x.strip()]

def normalize_url(raw):
    s = as_text(raw)
    if s is None: return None
    return s if re.match(r'^https?://', s, re.IGNORECASE) else None
FORMER_JEONNAM = {
    '목포시','여수시','순천시','나주시','광양시',
    '담양군','곡성군','구례군','고흥군','보성군','화순군','장흥군',
    '강진군','해남군','영암군','무안군','함평군','영광군',
    '장성군','완도군','진도군','신안군',
}

FORMER_GWANGJU = {'동구','서구','남구','북구','광산구'}

REGION_ALIASES = {
    '서울': '서울특별시', '서울시': '서울특별시', '서울특별시': '서울특별시',
    '경기': '경기도', '경기도': '경기도',
    '전남광주통합특별시': '전남광주통합특별시',
}

def normalized_region(raw):
    s = as_text(raw)
    return REGION_ALIASES.get(s, s)

def get_region(row):
    requested = normalized_region(row.get('requested_region'))
    sido_detail = normalized_region(row.get('detail_ctpvNm'))
    sido_list = normalized_region(row.get('ctpvNm'))
    sgg_detail = as_text(row.get('detail_sggNm'))
    sgg_list = as_text(row.get('sggNm'))
    sido = sido_detail or sido_list or requested
    sgg = sgg_detail or sgg_list
    reasons = []
    if sido_detail and sido_list and sido_detail != sido_list:
        reasons.append('list_detail_sido_conflict')
    if sgg_detail and sgg_list and sgg_detail != sgg_list:
        reasons.append('list_detail_sigungu_conflict')
    if requested and sido and requested != sido:
        reasons.append('requested_sido_conflict')
    if not sgg:
        reasons.append('missing_sigungu_scope_unverified')

    legacy = None
    if sido == '전남광주통합특별시':
        if sgg in FORMER_JEONNAM:
            legacy = 'former_jeonnam'
        elif sgg in FORMER_GWANGJU:
            legacy = 'former_gwangju'
        elif sgg:
            legacy = 'unknown'
            reasons.append('combined_region_unmapped_sigungu')
        else:
            legacy = 'unknown'
            reasons.append('combined_region_missing_sigungu')

    # 시군구 존재는 지역범위 후보일 뿐, 신청가능지역 확정 아님
    scope = 'sigungu' if sgg else 'unknown'
    return {
        'requested_region': requested,
        'raw_sido_name': as_text(row.get('detail_ctpvNm')) or as_text(row.get('ctpvNm')),
        'raw_sigungu_name': sgg_detail or sgg_list,
        'sido_name': sido,
        'sigungu_name': sgg,
        'region_code': None,
        'region_scope': scope,
        'region_scope_verified': False,
        'legacy_area_group': legacy,
        'region_review_status': 'pending' if reasons else 'provisional',
        'region_review_reasons': list(dict.fromkeys(reasons)),
    }
def normalize_policy(row):
    selected = {}
    sources = {}
    for new_name, candidates in FIELD_MAPPING.items():
        value, used = choose_field(row, candidates)
        selected[new_name] = value
        sources[new_name] = used

    region = get_region(row)
    fetched = row.get('detail_fetched')
    detail_fetched = fetched is True or str(fetched).strip().lower() in ('true','1')
    item = {
        'policy_id': str(row['servId']).strip(),
        'title': as_text(selected['title']),
        'summary': as_text(selected['summary']),
        'target_text': as_text(selected['target_text']),
        'selection_criteria_text': as_text(selected['selection_criteria_text']),
        'benefit_text': as_text(selected['benefit_text']),
        'application_text': as_text(selected['application_text']),
        'application_method_name': as_text(selected['application_method_name']),
        'department': as_text(selected['department']),
        'contact': as_text(selected['contact']),
        'start_date': parse_date(selected['start_date_raw']),
        'end_date': parse_date(selected['end_date_raw']),
        'updated_at_source': parse_date(selected['updated_at_source_raw']),
        'start_date_raw': as_text(selected['start_date_raw']),
        'end_date_raw': as_text(selected['end_date_raw']),
        'updated_at_source_raw': as_text(selected['updated_at_source_raw']),
        'life_stage_tags': parse_tags(selected['life_stage_tags']),
        'target_group_tags': parse_tags(selected['target_group_tags']),
        'interest_tags': parse_tags(selected['interest_tags']),
        'support_cycle': as_text(selected['support_cycle']),
        'provider_type': as_text(selected['provider_type']),
        'source_type': 'local_welfare_api',
        'source_url': normalize_url(row.get('servDtlLink')),
        'source_url_raw': as_text(row.get('servDtlLink')),
        'detail_fetched': detail_fetched,
        'field_sources': sources,
        **region,
    }
    return item

def normalize_rows(rows):
    raw_ids=[str(r.get('servId') or '').strip() for r in rows]
    if len(set(raw_ids))!=len(rows) or not all(raw_ids):
        raise ValueError('원본 servId 중복/누락')
    result=[normalize_policy(r) for r in rows]
    ensure_unique(result)
    return result

def run(input_path, output_path):
    rows=normalize_rows(read_jsonl(input_path))
    write_jsonl(output_path,rows)
    return {'normalized':len(rows),'output':str(output_path)}
