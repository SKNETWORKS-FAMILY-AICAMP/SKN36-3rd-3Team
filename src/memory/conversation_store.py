"""Small, explicit PostgreSQL store for chat sessions and chat messages.

No retrieval of welfare policies occurs here. Schema must be applied separately.
No DDL, table dropping or migrations occur automatically at runtime.
"""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID


def validate_session_id(session_id: str) -> str:
    """Require an actual UUID to avoid arbitrary identifiers/SQL injection risks."""
    try:
        parsed = UUID(str(session_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("session_id는 유효한 UUID 문자열이어야 합니다.") from exc
    return str(parsed)


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg가 필요합니다: pip install 'psycopg[binary]'") from exc
    from dotenv import load_dotenv
    load_dotenv()
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(".env에 DATABASE_URL을 설정해야 합니다.")
    return psycopg.connect(url, connect_timeout=5)


def load_history(session_id: str, max_messages: int = 8) -> list[dict[str, str]]:
    """Read up to max_messages most recent messages, returned oldest-to-newest.

    A missing session_id is not an error. Never creates a session on read.
    """
    sid = validate_session_id(session_id)
    if not 0 <= max_messages <= 40:
        raise ValueError("max_messages 범위는 0~40입니다.")
    if max_messages == 0:
        return []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT role, content FROM chat_messages
                   WHERE session_id = %s::uuid
                   ORDER BY message_id DESC LIMIT %s""",
                (sid, max_messages),
            )
            rows = cur.fetchall()
    return [{"role": role, "content": content} for role, content in reversed(rows)]


def save_exchange(session_id: str, question: str, answer: str) -> None:
    """Atomically insert a user/assistant pair. Duplicate requests aren't de-duplicated."""
    sid = validate_session_id(session_id)
    if not question.strip() or not answer.strip():
        raise ValueError("빈 질문이나 답변은 저장할 수 없습니다.")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO chat_sessions(session_id)
                   VALUES (%s::uuid)
                   ON CONFLICT (session_id)
                   DO UPDATE SET updated_at = now()""",
                (sid,),
            )
            cur.executemany(
                """INSERT INTO chat_messages(session_id, role, content)
                   VALUES (%s::uuid, %s, %s)""",
                [(sid, "user", question), (sid, "assistant", answer)],
            )


def delete_session(session_id: str) -> bool:
    """Delete one session and all its messages (ON DELETE CASCADE)."""
    sid = validate_session_id(session_id)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat_sessions WHERE session_id = %s::uuid", (sid,))
            return cur.rowcount > 0
