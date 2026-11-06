"""UI가 호출하는 유일한 답변 진입점. 미연결 시 Mock으로 몰래 대체하지 않습니다."""
import os
from .schemas import ChatResponse, UserProfile


def answer(question: str, profile: UserProfile) -> ChatResponse:
    question = question.strip()
    if not question:
        raise ValueError('질문을 입력해 주세요.')
    mode = os.getenv('USE_MOCK', 'true').strip().lower()
    if mode == 'true':
        from .mock import answer as backend_answer
    elif mode == 'false':
        from .rag_backend import answer as backend_answer
    else:
        raise ValueError('USE_MOCK는 true 또는 false여야 합니다.')
    response = backend_answer(question, profile)
    if not isinstance(response, ChatResponse):
        raise TypeError('백엔드는 ChatResponse를 반환해야 합니다.')
    return response
