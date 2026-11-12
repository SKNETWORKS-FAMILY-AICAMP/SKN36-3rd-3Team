from uuid import UUID

from backend.src.schemas.chat import ChatRegion
from src.agents.graph import ask_welfare


def process_chat(
    question: str,
    session_id: UUID | None = None,
    region: ChatRegion | None = None,
) -> dict:
    return ask_welfare(
        question=question,
        session_id=str(session_id) if session_id else None,
        region=region.model_dump() if region is not None else None,
        mock=False,
        memory_enabled=True,
    )
