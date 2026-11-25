
import re

NEED_RULES = {
    "meal_support": r"급식|무료급식|식사\s*지원|도시락|밑반찬|식사\s*배달",
    "mobility": r"이동지원|교통비\s*지원|보행보조|휠체어|보조기기",
    "housing": r"주거지원|주거급여|주택개조|주거환경개선|공공임대",
    "medical_care": r"의료비|건강보험료|진료비|치료비|건강검진",
    "financial_support": r"생활비|생계급여|생계비|생활안정|기초연금",
    "daily_care": r"방문요양|방문돌봄|일상생활지원|노인맞춤돌봄",
    "social_participation": r"사회참여|여가활동|문화활동|경로당",
    "employment": r"노인일자리|취업지원|일자리\s*지원",
    "mental_health": r"심리상담|정신건강|우울증|정서지원",
    "safety": r"응급안전|안전손잡이|낙상예방|안전확인",
    "energy_support": r"난방비|에너지바우처|연료비",
    "dementia_care": r"치매안심|치매환자\s*지원|치매검진",
    "hygiene": r"목욕비|이미용비|목욕\s*지원"
}


def extract_age(policy):

    evidence = []
    minimums = []
    maximums = []

    for field in ["target_text", "selection_criteria_text"]:

        text = str(policy.get(field) or "")

        for m in re.finditer(
            r"(?:만\s*)?(\d{1,3})\s*세\s*(이상|초과|이하|미만)",
            text
        ):
            age = int(m.group(1))
            operator = m.group(2)

            if not 0 <= age <= 120:
                continue

            evidence.append({
                "field": field,
                "raw_text": m.group(),
                "value": age,
                "operator": {
                    "이상": ">=",
                    "초과": ">",
                    "이하": "<=",
                    "미만": "<"
                }[operator],
                "review_status": "pending"
            })

            if operator == "이상":
                minimums.append(age)
            elif operator == "초과":
                minimums.append(age + 1)
            elif operator == "이하":
                maximums.append(age)
            elif operator == "미만":
                maximums.append(age - 1)

    # 복합 조건을 단일 연령 범위로 잘못 확정하지 않음
    age_min = None
    age_max = None

    if len(evidence) == 1:
        age_min = minimums[0] if minimums else None
        age_max = maximums[0] if maximums else None

    return {
        "age_min": age_min,
        "age_max": age_max,
        "age_evidence": evidence,
        "age_review_status": "needs_review"
    }


def extract_needs(policy):

    evidence = []

    for field in ["title", "summary", "benefit_text"]:

        text = str(policy.get(field) or "")

        for tag, pattern in NEED_RULES.items():

            match = re.search(pattern, text)

            if match:
                evidence.append({
                    "need_tag": tag,
                    "field": field,
                    "raw_text": match.group(),
                    "context": text[
                        max(0, match.start() - 40):
                        match.end() + 40
                    ],
                    "review_status": "pending"
                })

    return {
        "need_tags": sorted({
            e["need_tag"] for e in evidence
        }),
        "need_evidence": evidence,
        "need_review_status": "needs_review"
    }

