"""UI와 RAG가 공유하는 입력·출력 계약."""
from dataclasses import dataclass, field

SIGUNGU = ('창원시', '진주시', '통영시', '사천시', '김해시', '밀양시', '거제시',
           '양산시', '의령군', '함안군', '창녕군', '고성군', '남해군', '하동군',
           '산청군', '함양군', '거창군', '합천군')
CONDITIONS = ('혼자 사심', '소득이 적음', '치매', '장애', '거동 불편', '해당 없음')


@dataclass(frozen=True)
class UserProfile:
    sigungu: str
    age: int
    conditions: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.sigungu not in SIGUNGU:
            raise ValueError('경상남도 시·군을 선택해 주세요.')
        if type(self.age) is not int or not 0 <= self.age <= 120:
            raise ValueError('나이는 0~120 사이의 정수로 입력해 주세요.')
        if any(item not in CONDITIONS for item in self.conditions):
            raise ValueError('상황 목록에서 선택해 주세요.')
        if '해당 없음' in self.conditions and len(self.conditions) > 1:
            raise ValueError('해당 없음은 다른 상황과 함께 선택할 수 없어요.')


@dataclass(frozen=True)
class Source:
    title: str
    org: str
    url: str


@dataclass(frozen=True)
class ChatResponse:
    answer: str
    sources: list[Source] = field(default_factory=list)
    need_call_129: bool = False
