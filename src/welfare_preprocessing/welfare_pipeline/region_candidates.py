"""STEP 3-A: 통합 행정지역의 미확정 정책 자동 후보 추출; 확정하지 않음."""
import re,csv,json
from pathlib import Path
from .io_utils import read_jsonl,write_jsonl

TEXT_FIELDS = {
    'title': 5, 'department': 4, 'target_text': 4,
    'selection_criteria_text': 4, 'application_text': 3,
    'summary': 2, 'benefit_text': 2,
}

PATTERNS = {
    'jeonnam': [
        (r'전라남도|전남도청|전남도민|전남\s*주민', '전남 직접 명시'),
        (r'전남(?:교육청|복지재단|사회서비스원)', '전남 기관'),
        (r'\b(?:목포시|여수시|순천시|나주시|광양시|해남군|장성군|담양군|무안군|영암군|화순군|완도군|진도군|신안군|영광군|함평군|곡성군|구례군|고흥군|보성군|장흥군|강진군)\b', '구 전남 시군'),
    ],
    'gwangju': [
        (r'광주광역시|광주광역시청|광주시민|광주광역시민|광주광역시\s*거주', '광주 직접 명시'),
        (r'광주(?:광역시)?(?:사회서비스원|복지재단|광역치매센터)', '광주 기관'),
        (r'광산구(?:청|민|\s*거주)?', '광주 광산구'),
    ],
    'national': [
        (r'전국\s*(?:공통|민|어디서나|동일|단위)|전\s*국민|전국에\s*거주', '전국 대상 명시'),
        (r'거주\s*지역(?:에)?\s*관계없이|지역\s*제한\s*없(?:음|이)', '지역 제한 없음 명시'),
    ],
}

WEAK_PATTERNS = [
    (r'(?<!전남)광주(?!광역시)', '광주 단독 표현: 어느 광주인지/언급 목적 불명'),
    (r'보건복지부|중앙정부|국민연금공단', '중앙기관 언급만으로 전국 적용 불확실'),
    (r'통합특별시', '통합 행정명칭만으로 구 전남/광주 미판정'),
]

OTHER_REGION = re.compile(r'서울특별시|경기도|인천광역시|부산광역시|대구광역시|대전광역시|울산광역시|세종특별자치시|제주특별자치도|전북특별자치도|경상남도|경상북도|충청남도|충청북도|강원특별자치도')

def clean_text(x):
    return re.sub(r'\s+', ' ', str(x)).strip() if x is not None else ''

def short_evidence(text, start, end, radius=34):
    return text[max(0,start-radius): min(len(text), end+radius)]

def evidence_for(p):
    evidences=[]
    for field, weight in TEXT_FIELDS.items():
        val=clean_text(p.get(field))
        if not val: continue
        for label, rules in PATTERNS.items():
            for pattern, label_desc in rules:
                for m in re.finditer(pattern, val, flags=re.I):
                    evidences.append({'candidate':label,'field':field,'reason':label_desc,
                                      'matched':m.group(0), 'snippet':short_evidence(val, m.start(), m.end()),
                                      'weight':weight})
        for pattern, why in WEAK_PATTERNS:
            for m in re.finditer(pattern, val, flags=re.I):
                evidences.append({'candidate':'ambiguous','field':field,'reason':why,
                                  'matched':m.group(0), 'snippet':short_evidence(val, m.start(), m.end()),
                                  'weight':0})
        for m in OTHER_REGION.finditer(val):
            evidences.append({'candidate':'other_region','field':field,'reason':'다른 지역 명시',
                              'matched':m.group(0), 'snippet':short_evidence(val, m.start(), m.end()),
                              'weight':0})
    return evidences
def classify_candidate(p):
    ev = evidence_for(p)
    groups = {e['candidate'] for e in ev if e['candidate'] in ('jeonnam','gwangju','national')}
    other = any(e['candidate']=='other_region' for e in ev)
    weak = any(e['candidate']=='ambiguous' for e in ev)
    if len(groups)>1:
        candidate='unknown'; reason='여러 적용 지역을 시사하는 단서 충돌'
    elif other and groups:
        candidate='unknown'; reason='다른 지역과 함께 언급되어 범위 검토 필요'
    elif len(groups)==1:
        candidate=next(iter(groups)); reason='지역 단서 발견 — 실제 신청 대상 원문 검수 필요'
    else:
        candidate='unknown'; reason='적용 지역의 명시적 근거 없음' if not weak else '약한/모호한 단서만 존재'
    # 단서의 횟수를 신뢰도 점수로 오인하지 않도록 임의 확률값 생성하지 않음
    return {
        'policy_id':p.get('policy_id'), 'title':p.get('title'),
        'requested_region':p.get('requested_region'),
        'sido_name':p.get('sido_name'), 'sigungu_name':p.get('sigungu_name'),
        'department':p.get('department'), 'region_scope_original':p.get('region_scope'),
        'candidate_region':candidate,
        'candidate_reason':reason,
        'evidence_count':len(ev),
        'evidence_text':' | '.join(f"[{e['field']}] {e['matched']} ({e['reason']})" for e in ev[:12]),
        'evidences':ev,
        'review_status':'pending', 'confirmed_region':None,
        'review_note':None,
    }

def is_uncertain_combined(p):
    return (p.get('requested_region')=='전남광주통합특별시' or p.get('sido_name')=='전남광주통합특별시') and p.get('legacy_area_group')=='unknown'

def run(input_path,csv_path,jsonl_path=None):
    rows=read_jsonl(input_path)
    candidates=[classify_candidate(p) for p in rows if is_uncertain_combined(p)]
    path=Path(csv_path);path.parent.mkdir(parents=True,exist_ok=True)
    columns=['policy_id','title','requested_region','sido_name','sigungu_name','department','region_scope_original','candidate_region','candidate_reason','evidence_count','evidence_text','review_status','confirmed_region','review_note']
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(candidates)
    if jsonl_path: write_jsonl(jsonl_path,candidates)
    return {'candidates':len(candidates),'output':str(path)}
