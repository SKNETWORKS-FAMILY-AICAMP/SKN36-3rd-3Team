
from uuid import UUID

from src.memory.conversation_store import (
    load_history,
    delete_session,
)


def get_session_history(
    session_id: UUID,
    max_messages: int = 40,
) -> list[dict[str, str]]:
    return load_history(
        session_id=str(session_id),
        max_messages=max_messages,
    )


def remove_session(session_id: UUID) -> bool:
    return delete_session(str(session_id))
