
import logging

from fastapi import APIRouter, HTTPException

from backend.src.schemas.chat import ChatRequest, ChatResponse
from backend.src.services.chat_service import process_chat

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["Chat"],
)


@router.post(
    "/chat",
    response_model=ChatResponse,
)
def chat(request: ChatRequest):
    try:
        result = process_chat(
            question=request.question,
            session_id=request.session_id,
            region=request.region,
        )

        return ChatResponse.model_validate(result)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Chat processing failed")
        raise HTTPException(
            status_code=503,
            detail="챗봇 응답 생성에 실패했습니다.",
        ) from exc
