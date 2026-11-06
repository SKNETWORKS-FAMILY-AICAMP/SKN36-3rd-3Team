"""RAG 담당자가 이 함수의 본문만 실제 검색·답변 구현으로 교체합니다."""
from .schemas import ChatResponse, UserProfile


def answer(question: str, profile: UserProfile) -> ChatResponse:
    raise NotImplementedError('실제 RAG 연결은 아직 준비 중입니다.')
