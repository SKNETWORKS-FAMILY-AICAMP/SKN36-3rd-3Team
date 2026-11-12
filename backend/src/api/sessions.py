
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from backend.src.schemas.sessions import (
    SessionHistoryResponse,
    SessionDeleteResponse,
)
from backend.src.services.session_service import (
    get_session_history,
    remove_session,
)

router = APIRouter(
    prefix="/api/sessions",
    tags=["Sessions"],
)


@router.get(
    "/{session_id}/history",
    response_model=SessionHistoryResponse,
)
def get_history(
    session_id: UUID,
    limit: int = Query(default=40, ge=1, le=40),
):
    try:
        messages = get_session_history(
            session_id=session_id,
            max_messages=limit,
        )

        return SessionHistoryResponse(
            session_id=session_id,
            messages=messages,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="대화 기록을 불러오지 못했습니다.",
        ) from exc


@router.delete(
    "/{session_id}",
    response_model=SessionDeleteResponse,
)
def delete_chat_session(session_id: UUID):
    try:
        deleted = remove_session(session_id)

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="해당 대화 세션을 찾을 수 없습니다.",
            )

        return SessionDeleteResponse(
            session_id=session_id,
            deleted=True,
        )

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="대화 세션을 삭제하지 못했습니다.",
        ) from exc
