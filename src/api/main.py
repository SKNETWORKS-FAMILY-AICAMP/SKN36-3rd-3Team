
"""FastAPI entry point for the elderly welfare RAG chatbot."""

from __future__ import annotations

import os
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.agents.graph import ask_welfare

load_dotenv()

app = FastAPI(
    title="SKN36 Elderly Welfare AI API",
    description="LangGraph + Hybrid RAG chatbot backend",
    version="0.1.0",
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: UUID | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    safety_status: str
    answer_status: str
    session_id: str | None


@app.get("/health")
def health():
    """서버 프로세스 상태 확인. DB 연결 상태를 의미하지 않음."""
    return {"status": "ok", "service": "welfare-rag-api"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """기존 LangGraph ask_welfare() 호출."""

    mock_mode = (
        os.getenv("CHAT_API_MOCK", "false").lower() == "true"
    )

    try:
        result = ask_welfare(
            question=request.question,
            session_id=(
                str(request.session_id)
                if request.session_id is not None
                else None
            ),
            mock=mock_mode,
            memory_enabled=False if mock_mode else None,
        )

        if result.get("answer_status") == "error":
            raise HTTPException(
                status_code=503,
                detail="답변 생성 서비스에 문제가 발생했습니다.",
            )

        return ChatResponse(**result)

    except HTTPException:
        raise

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="질문 또는 세션 입력값을 확인해 주세요.",
        )

    except Exception:
        # API 키, DB 오류 등 내부 정보를 응답으로 노출하지 않는다.
        raise HTTPException(
            status_code=503,
            detail="AI 서비스 연결을 확인해 주세요.",
        )
