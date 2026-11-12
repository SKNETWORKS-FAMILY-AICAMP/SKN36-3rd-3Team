
import logging

from fastapi import APIRouter, HTTPException

from backend.src.schemas.policies import PolicyDetail
from backend.src.services.policy_service import get_policy_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/policies",
    tags=["Policies"],
)


@router.get("/{policy_id}", response_model=PolicyDetail)
def read_policy(policy_id: str):
    try:
        policy = get_policy_detail(policy_id)

        if policy is None:
            raise HTTPException(
                status_code=404,
                detail="해당 정책을 찾을 수 없습니다.",
            )

        return policy

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Policy detail lookup failed")
        raise HTTPException(
            status_code=503,
            detail="정책 상세 정보를 불러오지 못했습니다.",
        ) from exc
