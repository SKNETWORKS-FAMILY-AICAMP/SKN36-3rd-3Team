from uuid import UUID
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ChatRegion(BaseModel):
    kind: Literal["nationwide", "region"] = "nationwide"
    sido_name: str | None = Field(default=None, max_length=30)
    sigungu_name: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_location(self):
        if self.kind == "region" and not (self.sido_name or "").strip():
            raise ValueError("지역 선택 시 sido_name은 필수입니다.")
        if self.kind == "nationwide" and (self.sido_name or self.sigungu_name):
            raise ValueError("전국 선택에는 sido_name/sigungu_name을 입력하지 마세요.")
        return self


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="사용자 질문")
    session_id: UUID | None = Field(default=None, description="이전 대화를 이어갈 때 사용하는 세션 ID")
    region: ChatRegion | None = Field(default=None, description="선택 지역. 생략하면 기존 전국 검색과 동일")


class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    safety_status: str = "normal"
    answer_status: str
    choices: list[Any] = Field(default_factory=list)
