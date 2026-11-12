
from uuid import UUID

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    role: str
    content: str


class SessionHistoryResponse(BaseModel):
    session_id: UUID
    messages: list[MessageResponse] = Field(
        default_factory=list
    )


class SessionDeleteResponse(BaseModel):
    session_id: UUID
    deleted: bool
