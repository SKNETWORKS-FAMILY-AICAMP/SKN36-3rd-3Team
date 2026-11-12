
import logging

from fastapi import APIRouter, HTTPException

from backend.src.schemas.policies import (
    AskRequest,
    AskResult,
)
from backend.src.services.policy_service import search_policies

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["Policies"],
)


@router.post("/ask", response_model=AskResult)
def ask_policy(request: AskRequest):
    try:
        return search_policies(request)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception("Policy search failed")
        raise HTTPException(
            status_code=503,
            detail="복지 정책을 검색하지 못했습니다.",
        ) from exc
