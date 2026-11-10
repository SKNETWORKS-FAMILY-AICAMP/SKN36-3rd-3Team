"""STEP 4: 정책별 direct/indirect/review/exclude_candidate 분류.
선별 파일에는 direct+indirect만 포함; review는 LLM 재분류를 위해 별도 보존.
"""
import re,csv,json
from pathlib import Path
from .io_utils import read_jsonl,write_jsonl,ensure_unique,new_run_dir

DIRECT_RULES = {
    '노인·고령자 명시': r'노인|고령자|고령층|어르신|시니어|노년층|노령층|독거노인',
    '65세 이상 명시': r'(?:만\s*)?65\s*세\s*(?:이상|부터|이후)|65\s*세\s*이상',
    '노인 전용 제도': r'기초연금|노인맞춤돌봄|노인일자리|장기요양|경로당|치매안심센터|경로우대',
}

INDIRECT_RULES = {
    '기초생활·생계': r'기초생활보장|생계급여|차상위|저소득층|긴급복지|긴급지원',
    '의료·건강': r'의료급여|의료비\s*지원|건강보험료\s*지원|재난적\s*의료비',
    '주거·에너지': r'주거급여|에너지바우처|난방비\s*지원|주거취약|공공임대',
    '장애·돌봄': r'장애인\s*(?:연금|지원|복지)|장애인활동지원|돌봄서비스',
}

EXCLUSIVE_RULES = {
    '영유아·아동': r'영유아|어린이집|아동수당|초등학생|미취학아동|아이돌봄',
    '청소년·학교': r'청소년|고등학생|중학생|학교급식|학자금|고교생',
    '청년 한정': r'청년\s*(?:전용|만|월세|수당|취업)|청년기본소득',
    '임신·출산': r'임산부|임신부|산모|출산지원금|산후조리|난임시술',
}

FOCUS_FIELDS = ('title', 'target_text', 'selection_criteria_text', 'life_stage_tags', 'target_group_tags')

CONTEXT_FIELDS = ('summary', 'benefit_text', 'application_text', 'interest_tags')

def to_text(value):
    if value is None:
        return ''
    if isinstance(value, (list, tuple, set)):
        return ' '.join(str(v) for v in value if v is not None)
    if isinstance(value, dict):
        return ' '.join(str(v) for v in value.values() if v is not None)
    return str(value).strip()

def collect_hits(p, fields, rules):
    hits=[]
    for field in fields:
        val=to_text(p.get(field))
        if not val:
            continue
        for label, pattern in rules.items():
            for match in list(re.finditer(pattern, val, flags=re.IGNORECASE))[:2]:
                lo=max(0, match.start()-28); hi=min(len(val), match.end()+28)
                hits.append({'field':field, 'rule':label, 'keyword':match.group(0), 'context':val[lo:hi]})
    return hits
NEGATIVE_AGE_PATTERN = r'(?:만\s*)?65\s*세\s*(?:미만|이하)|노인\s*(?:제외|미포함)|고령자\s*(?:제외|미포함)'

def classify_elderly(p):
    direct_focus=collect_hits(p,FOCUS_FIELDS,DIRECT_RULES)
    direct_context=collect_hits(p,CONTEXT_FIELDS,DIRECT_RULES)
    indirect_focus=collect_hits(p,FOCUS_FIELDS,INDIRECT_RULES)
    indirect_context=collect_hits(p,CONTEXT_FIELDS,INDIRECT_RULES)
    exclusive_focus=collect_hits(p,FOCUS_FIELDS,EXCLUSIVE_RULES)
    negative_age=[]
    for field in FOCUS_FIELDS:
        val=to_text(p.get(field))
        for m in re.finditer(NEGATIVE_AGE_PATTERN,val):
            negative_age.append({'field':field,'rule':'연령 상한/배제 표현','keyword':m.group(),'context':val[max(0,m.start()-24):m.end()+24]})
    direct=direct_focus or direct_context
    indirect=indirect_focus or indirect_context
    if negative_age or (direct and exclusive_focus):
        category='review'
        reason='노인 관련 단서와 제한 조건이 혼재하여 자격 검증 필요'
    elif direct_focus:
        category='direct'
        reason='정책명·지원대상·태그에 직접 노인 관련 근거 발견'
    elif direct_context:
        category='review'
        reason='본문에 노인 키워드가 있으나 정책 대상임을 확정할 근거 부족'
    elif indirect:
        category='indirect'
        reason='일반 복지정책 관련 단서 발견(노인 신청 가능성은 개별 검증 필요)'
    elif exclusive_focus:
        category='exclude_candidate'
        reason='정책명·대상·태그에서 비노인 대상 전용 단서 발견'
    else:
        category='review'
        reason='노인 관련성 또는 제외 근거가 불충분함'
    hits=(direct_focus+direct_context+indirect_focus+indirect_context+exclusive_focus+negative_age)
    # 동일 근거 중복 제거, 크기 제한
    seen=set(); unique=[]
    for h in hits:
        k=(h['field'],h['rule'],h['keyword'],h['context'])
        if k not in seen:
            seen.add(k);unique.append(h)
    return {
        **p,
        'elderly_candidate_category': category,
        'elderly_classification_reason':reason,
        'elderly_evidence':unique[:30],
        'elderly_review_status':'pending',
        'elderly_classification_method':'keyword_rules_v1',
        'elderly_eligibility_verified':False,
    }

def run(input_path,output_base):
    policies=read_jsonl(input_path);ensure_unique(policies)
    classified=[classify_elderly(p) for p in policies]
    selected=[p for p in classified if p['elderly_candidate_category'] in ('direct','indirect')]
    review=[p for p in classified if p['elderly_candidate_category']=='review']
    excluded=[p for p in classified if p['elderly_candidate_category']=='exclude_candidate']
    assert len(selected)+len(review)+len(excluded)==len(policies)
    run_dir=new_run_dir(output_base)
    for name,rows in [('policies_elderly_selected.jsonl',selected),('policies_elderly_review.jsonl',review),('policies_elderly_excluded_candidates.jsonl',excluded),('policies_all_with_elderly_labels.jsonl',classified)]:write_jsonl(run_dir/name,rows)
    # 원 노트북과 동일하게 전체 정책 분류 요약을 CSV로 저장 (review만이 아님)
    columns=['policy_id','title','elderly_candidate_category','elderly_classification_reason','elderly_review_status','elderly_classification_method','elderly_eligibility_verified','confirmed_category','review_note']
    with (run_dir/'elderly_classification_review.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader()
        for p in classified:
            w.writerow({**{k:p.get(k) for k in columns},'confirmed_category':'','review_note':''})
    return {'selected':len(selected),'review':len(review),'excluded_candidates':len(excluded),'run_dir':str(run_dir)}
