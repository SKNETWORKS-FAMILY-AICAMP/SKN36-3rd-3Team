"""실제 검색이나 자격 판정을 하지 않는 화면 시연용 응답."""
from .schemas import ChatResponse, Source, UserProfile


def answer(question: str, profile: UserProfile) -> ChatResponse:
    topics = (
        (('연금',), '기초연금은 나이와 소득 등 신청 조건을 확인해야 해요.'),
        (('돌봄', '혼자', '거동'), '돌봄 서비스는 생활 상황에 따라 이용 조건이 달라요.'),
        (('시설', '복지관'), '복지시설은 사시는 시·군의 담당 기관에 위치와 이용 조건을 확인해 주세요.'),
        (('치매',), '치매 관련 도움은 거주 지역의 상담 기관을 확인해 주세요.'),
    )
    for keywords, message in topics:
        if any(keyword in question for keyword in keywords):
            return ChatResponse(
                f'[시연용 예시] {profile.sigungu}, {profile.age}세 기준으로 질문하셨어요. '
                f'{message}\n\n이 화면은 실제 지원 대상이나 가까운 시설을 조회하지 않아요. '
                '최종 확인은 주민센터 또는 129에 문의해 주세요.',
                [Source('보건복지상담센터 (예시 참고 링크)', '보건복지상담센터',
                        'https://www.129.go.kr/index.do')],
            )
    return ChatResponse('확실한 답을 찾지 못했어요. 질문을 조금 더 자세히 적어 주세요. '
                        '129로 전화해 보세요.', need_call_129=True)
