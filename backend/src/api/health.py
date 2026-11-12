
from fastapi import APIRouter, HTTPException

from src.memory.conversation_store import _connect

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/health/db")
def database_health_check():
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()

        if result != (1,):
            raise RuntimeError("Unexpected database response")

        return {
            "status": "ok",
            "database": "postgresql",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL connection failed",
        ) from exc
