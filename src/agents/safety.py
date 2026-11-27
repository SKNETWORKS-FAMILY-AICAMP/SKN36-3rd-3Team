"""MVP 안전 분기: 규칙 기반 최소 구현.

의학적 위험 진단이나 전문적 위기 평가가 아닙니다. 실제 운영 전
한국어 문맥 테스트, 전문가 검토, 지원기관 최신정보 검증이 필요합니다.

단계 (팀 운영 기준. data/eval/v4/safety_questions_draft.jsonl 로 확인)
- urgent   : 복지 검색을 멈추고 정해 둔 안전 안내를 먼저 내보낸다. LLM·DB 없이 동작한다.
             임박한 위험을 확정했다는 뜻이 아니라 "안전 안내가 먼저"라는 뜻이다.
- distress : 검색은 계속하되, 마음·상황을 먼저 확인하도록 답변 단계에 지침을 주고
             필요한 상담 전화를 답변 끝에 붙인다. (평가 세트의 "확인 먼저"에 해당)
- normal   : 일반 처리.

정규식은 놓치는 표현이 있을 수밖에 없다. 여기서 normal 이 나왔다고 안전하다는 뜻은 아니다.
"""
from __future__ import annotations
import re
from .state import WelfareState, SafetyStatus

# ───────────── 스스로를 해칠 뜻 ─────────────

# "죽고 싶을 만큼 아파"처럼 정도를 나타내는 말. 통증 호소인지 위기인지 문장만으로 알 수 없어 확인을 먼저 한다.
_DEATH_AS_DEGREE = re.compile(r"죽[고구]\s*싶을\s*(?:만큼|정도|지경)")

_SELF_HARM = re.compile(
    # 직접 말함 ("죽고만 싶어"도 포함. "죽고 싶지는 않아"는 제외)
    r"죽[고구](?:만|도)?\s*싶(?!지)|"
    r"자살\s*(?:하[고구]\s*싶(?!지)|할\s*거|하려)|"
    r"죽어\s*버리[고구]\s*싶(?!지)|"
    r"(?:더\s*이상\s*|더는\s*)?살고\s*싶지\s*않|"
    r"살기\s*싫어|"
    r"목숨을\s*끊|"
    r"스스로\s*목숨|"
    r"나를\s*해치|"
    r"(?:스스로|내\s*자신|나\s*자신|제\s*자신)(?:에게|한테|을|를)?\s*(?:해코지|해치|다치게)|"
    r"자해\s*(?:하[고구]\s*싶(?!지)|할\s*거|하려)|"
    # 돌려 말함 (2026-11-27 팀 결정: 확인 먼저가 아니라 안전 안내를 먼저)
    r"죽는\s*(?:게|것이|편이)\s*(?:낫|나아|나을)|"
    r"그만\s*살(?:고\s*싶(?!지)|래|란다|아야)|"
    r"(?:내가|나만|나\s*하나)\s*(?:없어지|사라지|죽)(?:는\s*게|는\s*편이|면)[^.?!]{0,12}(?:낫|편하|좋)|"
    r"눈(?:을)?\s*(?:안|못)\s*떴으면|(?:안\s*깨어났|깨어나지\s*(?:않|말)았)으면|"
    r"살아서\s*(?:뭐|뭘|무엇)\s*(?:하|해)|"
    # "집을 살 생각이 없어요"(사다)와 헷갈리지 않게, 바로 앞에 목적어(…을/를)가 있으면 제외한다.
    r"(?<![을를]\s)살\s*(?:이유|의미|가치|마음|생각)[가이도]?\s*없|"
    r"내가[^.?!]{0,12}(?:없어지|사라지)면[^.?!]{0,15}(?:편해|편하|낫|좋)|"
    r"(?:삶|인생|생)을?[^.?!]{0,8}(?:마치|끝내|마감|정리하)[고구]\s*싶(?!지)|"
    r"(?:다|모든\s*걸|전부)\s*끝내[고구]\s*싶(?!지)|"
    r"(?:영감|할멈|남편|아내|집사람|바깥양반)\s*(?:을|를)?\s*따라\s*가[고구]\s*싶(?!지)"
)

# ───────────── 남을 해칠 뜻 ─────────────

_HARM_OTHERS = re.compile(
    r"(?:사람|누군가|그\s*사람|저\s*사람|가족|이웃)(?:을|를)?\s*(?:죽이|해치|살해)|"
    r"(?:죽여\s*버리|해쳐\s*버리)|"
    r"(?:다치게|해코지)[^.?!]{0,6}(?:하고\s*말|할\s*거|하겠|하고\s*싶(?!지))"
)

# ───────────── 응급 증상 ─────────────

_EMERGENCY = re.compile(
    r"숨(?:이|을)?\s*(?:제대로\s*|잘\s*)?(?:안\s*쉬어|못\s*쉬|막혀|넘어가)|"
    r"가슴이?[^.?!]{0,10}(?:짓눌|조여|쥐어짜)|"
    # 쓰러짐: 지금 벌어진 일로 보이는 꼴만 ("남편이 쓰러져서 간병하느라…" 같은 사정 설명은 제외)
    r"(?:방금|지금|갑자기|막)[^.?!]{0,10}쓰러(?:져|졌)|"
    r"쓰러(?:져|졌)[^.?!]{0,12}(?:말을?\s*못|의식|숨|대답이?\s*없|안\s*(?:일어나|움직)|도와|어떡|어떻게)|"
    r"의식(?:이|을)?\s*(?:없|잃)|"
    r"(?:갑자기|쓰러져서?)\s*말(?:을|이)?\s*(?:못|안\s*나와|어눌)|"
    r"한쪽\s*(?:팔|다리|얼굴)[^.?!]{0,8}(?:마비|힘이\s*(?:없|빠))|"
    r"피를\s*(?:많이\s*)?(?:흘리|토하|토했)|"
    r"경련|발작"
)
# 지난 일을 말하는 경우("작년에 쓰러졌었어")는 지금의 응급이 아니다. 문장마다 따로 본다
# ("예전에 쓰러졌어요. 지금은 숨을 못 쉬겠어요."의 뒤 문장은 지금의 응급이다).
_PAST = re.compile(r"작년|재작년|예전|옛날|지난\s*(?:달|해|번|주)|(?:년|달|개월|해)\s*전")


def _emergency_now(text: str) -> bool:
    return any(_EMERGENCY.search(s) and not _PAST.search(s) for s in re.split(r"[.?!]", text))

# ───────────── 학대 ─────────────

_FAMILY = (r"(?:아들|딸|며느리|사위|남편|아내|영감|할멈|손자|손녀|자식|아버지|어머니|엄마|아빠|형(?:이|님|한테|에게)|동생|오빠|누나|언니|"
           r"요양보호사|간병인|보호사)")
# "맞다"는 뜻이 여럿이다(주사를 맞다, 말이 맞다, 비를 맞다). 사람에게 맞는다는 뜻이 분명한 꼴만 쓴다.
_VIOLENCE = (r"(?:때려(?!치)|때린|때립|때리(?!치)|두들겨|폭행|구타|손찌검|밀쳐|발로\s*차|목을\s*조|"
             r"(?:한테|에게)\s*(?:얻어\s*)?맞|얻어\s*맞|맞고\s*(?:살|사는|사시|지내))")
# 말하는 사람 자신이 당하고 있는 경우. 이웃 이야기가 섞여 있어도("이웃이 보는 앞에서 아들이 저를 때려요") 이쪽이 먼저다.
_ABUSE_SELF = re.compile(rf"(?:나를|날|저를|나한테|저한테)\s*{_VIOLENCE}")
_ABUSE_VIOLENCE = re.compile(rf"{_FAMILY}[^.?!]{{0,20}}{_VIOLENCE}")
# 이웃·지인의 일을 알리는 경우. 지금 벌어지는 일인지 확인이 먼저다.
_ABUSE_REPORT = re.compile(rf"(?:옆집|이웃|윗집|아랫집|앞집|동네|친구|아는\s*(?:분|사람))[^.?!]{{0,25}}(?:{_VIOLENCE}|학대|굶|가둬|가두)")
# 학대 의심: 가족·돌보는 사람이 나오고, 방임·돈 통제·모욕 가운데 하나가 함께 나올 때 (말의 순서는 상관없음)
_FAMILY_RE = re.compile(_FAMILY)
_ABUSE_SIGNS = re.compile(
    r"(?:밥|끼니|먹을\s*걸|약|병원)[^.?!]{0,25}(?:안\s*줘|안\s*준|못\s*가게|모른\s*척)|"            # 방임
    r"(?:통장|도장|연금|돈|카드|집문서)[^.?!]{0,25}(?:가져가|뺏|빼앗|안\s*돌려|마음대로|못\s*쓰게)|"          # 경제적 학대
    r"욕을?\s*(?:해|하|퍼)|구박|나가라고|가둬|가두"                                                        # 정서적 학대·감금
)

# ───────────── 사기 의심 ─────────────

_SCAM = re.compile(
    # 기관·수사관을 자처하면서 돈·계좌 이야기를 하는 경우
    r"(?:검찰|경찰|금감원|금융감독원|국세청|법원|수사관|검사|형사)"
    r"(?:이라면서|이라며|라면서|라며|이라고|라고|이라는|라는|을?\s*사칭)[^.?!]{0,30}"
    r"(?:돈|계좌|통장|비밀번호|현금|상품권|이체|송금)|"
    # 비밀번호를 알려 달라는 요구 (정상적인 은행 업무에서는 남이 묻지 않는다)
    r"(?:계좌|통장|카드)\s*비밀번호[^.?!]{0,12}(?:알려\s*달|불러\s*달|말해\s*달|달래|요구|대라|대래|알려\s*줘도)|"
    r"보이스\s*피싱|전화\s*금융\s*사기"
)

# ───────────── 확인 먼저 (distress) ─────────────

_SYMPTOM = re.compile(
    r"어지러|어지럽|머리가\s*(?:너무\s*|자꾸\s*)?(?:아프|핑\s*도)|메슥|울렁|식은땀|숨이\s*차|가슴이\s*(?:답답|두근)|토했|구토|열이\s*(?:나|높)"
)
_BEREAVEMENT = re.compile(
    r"(?:영감|할멈|남편|아내|집사람|바깥양반|자식|아들|딸)[^.?!]{0,12}"
    r"(?:죽고|죽은|먼저\s*가|세상을\s*떠|떠나고|보내고|여의고|잃고)[^.?!]{0,15}(?:혼자|저만|나만|빈\s*집|외롭|적적|허전)"
)
_DISTRESS = re.compile(
    r"(?:너무\s*)?외로워|고립된\s*느낌|우울해|우울합니다|살기\s*힘들|"
    r"희망이\s*없|아무도\s*(?:안\s*찾아|찾아오지)|마음이\s*(?:너무\s*힘들|허전)|"
    r"(?:말할|얘기할|이야기할)\s*(?:사람|일)이?\s*없|"
    r"사는\s*게\s*(?:재미|낙)[가이도]?\s*없|낙이\s*없|의욕이\s*없|아무것도\s*하기\s*싫|짐만\s*(?:돼|되|될)|"
    r"즐겁지\s*(?:가\s*)?않|기운(?:도|이)?\s*(?:안\s*나|없)"
)


def classify_safety(question: str) -> tuple[SafetyStatus, str]:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 비어 있을 수 없습니다.")
    text = re.sub(r"\s+", " ", question.strip().lower())
    # "죽고 싶을 만큼"은 정도 표현이므로 떼어 내고 나머지에서 위기 표현을 찾는다.
    without_degree = _DEATH_AS_DEGREE.sub(" ", text)
    if _SELF_HARM.search(without_degree):
        return "urgent", "self_harm_signal"
    if _HARM_OTHERS.search(text):
        return "urgent", "harm_to_others_signal"
    if _emergency_now(text):
        return "urgent", "emergency_symptom_signal"
    if _ABUSE_SELF.search(text):
        return "urgent", "abuse_signal"
    if _ABUSE_REPORT.search(text):
        return "distress", "abuse_report_signal"
    if _ABUSE_VIOLENCE.search(text):
        return "urgent", "abuse_signal"
    if _SCAM.search(text):
        return "urgent", "scam_signal"
    if _FAMILY_RE.search(text) and _ABUSE_SIGNS.search(text):
        return "distress", "abuse_suspected_signal"
    if _DEATH_AS_DEGREE.search(text):
        return "distress", "death_phrase_as_degree_signal"
    if _SYMPTOM.search(text):
        return "distress", "symptom_signal"
    if _BEREAVEMENT.search(text):
        return "distress", "bereavement_signal"
    if _DISTRESS.search(text):
        return "distress", "emotional_distress_signal"
    return "normal", "no_explicit_signal"


def safety_node(state: WelfareState) -> WelfareState:
    status, reason = classify_safety(state["question"])
    return {"safety_status": status, "safety_reason": reason}


def route_after_safety(state: WelfareState) -> str:
    return "urgent" if state.get("safety_status") == "urgent" else "continue"


# 긴급 안내 문구. 전화번호는 평가 세트에 근거(공식 자료 청크)를 적어 둔 것만 쓴다: 109, 1577-1389, 129, 1355.
# 119·112 는 국가 긴급전화다.
_URGENT_ANSWERS = {
    "harm_to_others_signal": (
        "말씀해 주셔서 감사합니다. 지금 누군가를 다치게 할 가능성이 있다면 "
        "상대방과 거리를 두고 위험한 물건에서 멀어져 주세요. "
        "위험이 임박했다면 한국에서는 112에 연락해 도움을 요청해 주세요. "
        "지금 안전한 곳에 계신가요?"
    ),
    "self_harm_signal": (
        "많이 힘드신 상황인 것 같아요. 지금 혼자 감당하지 않으셔도 됩니다. "
        "자살예방상담전화 109에 전화하시면 이야기를 들어 드립니다. "
        "가능하면 가까이 있는 믿을 만한 사람에게 지금 상황을 알려 주세요. "
        "스스로를 다치게 할 위험이 지금 있다면 119 또는 112에 즉시 연락해 주세요. "
        "지금은 안전한 곳에 계신가요?"
    ),
    "emergency_symptom_signal": (
        "지금 바로 119에 전화해 주세요. "
        "주변에 사람이 있으면 도움을 청해 주세요. "
        "저는 증상을 진단할 수 없으니 기다리지 말고 119의 안내를 따라 주세요."
    ),
    "abuse_signal": (
        "말씀해 주셔서 감사합니다. 많이 놀라고 힘드셨겠어요. 지금은 안전한 곳에 계신가요? "
        "지금 위험하다면 112에 바로 연락해 주세요. "
        "노인보호전문기관 1577-1389에서 상담과 보호를 도와 드립니다. "
        "보건복지상담센터 129로도 도움을 요청하실 수 있어요."
    ),
    "scam_signal": (
        "사기일 수 있어요. 돈을 보내거나 비밀번호·계좌번호를 알려 주지 말고 우선 전화를 끊어 주세요. "
        "그 기관의 공식 전화번호로 직접 다시 확인해 보세요. "
        "사기가 의심되거나 이미 보냈거나 알려 주었다면 112에 신고해 주세요."
    ),
}
_PENSION_SCAM_NOTE = " 기초연금에 대해 궁금한 점은 국민연금공단 1355나 주민센터에 직접 전화해 확인하세요."


def urgent_response_node(state: WelfareState) -> WelfareState:
    reason = state.get("safety_reason")
    answer = _URGENT_ANSWERS.get(reason, _URGENT_ANSWERS["self_harm_signal"])
    if reason == "scam_signal" and "연금" in str(state.get("question") or ""):
        answer += _PENSION_SCAM_NOTE
    return {"answer": answer, "answer_status": "safety_response", "sources": []}


# 확인 먼저(distress): 답변을 만드는 LLM 에게 주는 지침. 사유마다 무엇을 먼저 확인할지가 다르다.
_DISTRESS_GUIDANCE = {
    "emotional_distress_signal": "먼저 짧게 공감하고 이용 가능한 지원 정보만 근거와 함께 안내하세요.",
    "bereavement_signal": "먼저 위로하고 요즘 마음이 어떤지, 어떻게 지내시는지 직접 물어보세요. 우울증이라고 진단하지 마세요.",
    "death_phrase_as_degree_signal": (
        "아픈 것에 대한 도움을 안내하되, 많이 아프다는 뜻인지 죽고 싶다는 생각이 드는지 구분해서 조심스럽게 물어보세요. "
        "과장해서 한 말이라고 단정하지 마세요."
    ),
    "symptom_signal": (
        "병명을 추정하거나 약을 추천하지 마세요. 지금 상태가 어떤지, 다른 증상이 함께 있는지 묻고 병원·보건소 진료를 권하세요."
    ),
    "abuse_suspected_signal": (
        "가족 사이의 일이라며 넘기지 말고, 본인 뜻에 반하는 일인지와 지금 위협이나 폭력이 있는지, 식사는 하고 계신지 조심스럽게 물어보세요. "
        "확인 없이 학대라고 단정하지 마세요."
    ),
    "abuse_report_signal": (
        "지금 폭력이 벌어지고 있는지 물어보세요. 확실하지 않아도 신고·상담할 수 있다고 알려 주세요."
    ),
}

# 답변 끝에 반드시 붙는 확인 질문과 상담 전화. LLM 이 빠뜨리거나, 검색 없이 끝나거나(되묻기·근거 부족),
# LLM 이 실패한 경로에서도 "확인 먼저"가 지켜지게 한다.
_DISTRESS_NOTES = {
    "emotional_distress_signal": "요즘 어떻게 지내고 계신지 조금 더 이야기해 주시겠어요?",
    "bereavement_signal": (
        "혼자 지내시면서 요즘 마음은 어떠세요? 괜찮으시면 조금 더 이야기해 주세요. "
        "마음이 계속 힘드시면 정신건강위기 상담전화 1577-0199에서 이야기를 나누실 수 있어요."
    ),
    "death_phrase_as_degree_signal": (
        "많이 아프셔서 하신 말씀인지, 정말 죽고 싶다는 생각이 드시는지 여쭤봐도 될까요? "
        "그런 생각이 드신다면 자살예방상담전화 109에 꼭 전화해 주세요."
    ),
    "symptom_signal": (
        "지금은 좀 어떠세요? 다른 증상도 함께 있는지 알려 주세요. "
        "증상이 심하거나 갑자기 나빠지면 바로 119에 전화해 주세요. "
        "저는 진단을 할 수 없으니 병원이나 보건소 진료를 권해 드려요."
    ),
    "abuse_suspected_signal": (
        "원하지 않는데 그렇게 된 일인지, 지금 위협을 받거나 식사를 못 하고 계신 건 아닌지 여쭤봐도 될까요? "
        "노인보호전문기관 1577-1389에서 상담받으실 수 있어요. 지금 위험하다면 112에 연락해 주세요."
    ),
    "abuse_report_signal": (
        "지금 폭력이 벌어지고 있나요? 그렇다면 112에 바로 연락해 주세요. "
        "확실하지 않아도 노인보호전문기관 1577-1389에 신고·상담하실 수 있고, 신고자의 비밀은 보장됩니다."
    ),
}


def distress_guidance(reason: str | None) -> str:
    """답변 단계 프롬프트에 붙일 지침. 모르는 사유면 기본 공감 지침."""
    return _DISTRESS_GUIDANCE.get(reason or "", _DISTRESS_GUIDANCE["emotional_distress_signal"])


def safety_note_node(state: WelfareState) -> WelfareState:
    """확인 먼저(distress) 단계에서 사유에 맞는 확인 질문과 상담 전화를 답변 끝에 붙인다. 그 밖에는 아무것도 바꾸지 않는다."""
    if state.get("safety_status") != "distress":
        return {}
    note = _DISTRESS_NOTES.get(state.get("safety_reason") or "")
    answer = str(state.get("answer") or "")
    if not note or not answer.strip() or note in answer:
        return {}
    return {"answer": f"{answer.rstrip()}\n\n{note}"}


def pending_retrieval_node(state: WelfareState) -> WelfareState:
    """2단계의 명시적 임시 노드. DB/LLM이 작동한다고 가장하지 않음."""
    if state.get("safety_status") == "distress":
        answer = (
            "힘든 마음을 이야기해 주셔서 감사합니다. "
            "지금은 복지정보 검색 기능을 연결하는 중이라 확인된 정책을 안내하기 어렵습니다. "
            "원하시면 어떤 도움이 필요한지 함께 정리해 볼게요."
        )
    else:
        answer = (
            "현재 복지정보 검색 기능을 연결하는 중입니다. "
            "정책 조건과 공식 출처를 확인한 뒤 안내할 수 있습니다."
        )
    return {"answer": answer, "answer_status": "no_evidence", "sources": []}
