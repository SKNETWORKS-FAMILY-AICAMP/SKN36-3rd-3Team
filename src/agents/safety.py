"""MVP 안전 분기: 규칙 기반 최소 구현.

의학적 위험 진단이나 전문적 위기 평가가 아닙니다. 실제 운영 전
한국어 문맥 테스트, 전문가 검토, 지원기관 최신정보 검증이 필요합니다.
"""
from __future__ import annotations
import re
from .state import WelfareState, SafetyStatus

# 위기 표현을 의도적으로 좁게 설정. 단순 불만/외로움은 차단하지 않음.
_SELF_HARM = re.compile(
    r"죽고\s*싶|자살\s*(?:하고\s*싶|할\s*거|하려)|목숨을\s*끊|"
    r"스스로\s*목숨|나를\s*해치|자해\s*(?:하고\s*싶|할\s*거|하려)"
)
_HARM_OTHERS = re.compile(
    r"(?:사람|누군가|그\s*사람|저\s*사람|가족|이웃)(?:을|를)?\s*(?:죽이|해치|살해)|"
    r"(?:죽여\s*버리|해쳐\s*버리)"
)
_DISTRESS = re.compile(
    r"(?:너무\s*)?외로워|고립된\s*느낌|우울해|우울합니다|살기\s*힘들|"
    r"희망이\s*없|아무도\s*(?:안\s*찾아|찾아오지)|마음이\s*너무\s*힘들"
)


def classify_safety(question: str) -> tuple[SafetyStatus, str]:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question은 비어 있을 수 없습니다.")
    text = re.sub(r"\s+", " ", question.strip().lower())
    if _SELF_HARM.search(text):
        return "urgent", "self_harm_signal"
    if _HARM_OTHERS.search(text):
        return "urgent", "harm_to_others_signal"
    if _DISTRESS.search(text):
        return "distress", "emotional_distress_signal"
    return "normal", "no_explicit_signal"


def safety_node(state: WelfareState) -> WelfareState:
    status, reason = classify_safety(state["question"])
    return {"safety_status": status, "safety_reason": reason}


def route_after_safety(state: WelfareState) -> str:
    return "urgent" if state.get("safety_status") == "urgent" else "continue"


def urgent_response_node(state: WelfareState) -> WelfareState:
    if state.get("safety_reason") == "harm_to_others_signal":
        answer = (
            "말씀해 주셔서 감사합니다. 지금 누군가를 다치게 할 가능성이 있다면 "
            "상대방과 거리를 두고 위험한 물건에서 멀어져 주세요. "
            "위험이 임박했다면 한국에서는 112에 연락해 도움을 요청해 주세요. "
            "지금 안전한 곳에 계신가요?"
        )
    else:
        answer = (
            "많이 힘드신 상황인 것 같아요. 지금 혼자 감당하지 않으셔도 됩니다. "
            "가능하면 가까이 있는 믿을 만한 사람에게 지금 상황을 알려 주세요. "
            "스스로를 다치게 할 위험이 지금 있다면 한국에서는 119 또는 112에 즉시 연락해 주세요. "
            "지금은 안전한 곳에 계신가요?"
        )
    return {"answer": answer, "answer_status": "safety_response", "sources": []}


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
