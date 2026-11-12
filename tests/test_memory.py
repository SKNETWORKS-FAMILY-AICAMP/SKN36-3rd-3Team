"""No live PostgreSQL/LLM required: inject mocks to verify session orchestration."""
from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import UUID

from src.memory.conversation_store import validate_session_id
from src.memory.session_manager import run_chat_session


class MemoryTests(unittest.TestCase):
    def test_invalid_session_id(self):
        with self.assertRaises(ValueError):
            validate_session_id("not-an-id")

    @patch("src.memory.session_manager.save_exchange")
    @patch("src.memory.session_manager.load_history", return_value=[])
    def test_new_session_creates_uuid_and_saves(self, load, save):
        def run(state):
            self.assertEqual(state["history"], [])
            return {"answer": "신청처를 확인해 주세요.", "answer_status": "success", "safety_status": "normal", "sources": []}
        result = run_chat_session("기초연금 신청", None, run)
        UUID(result["session_id"])
        save.assert_called_once_with(result["session_id"], "기초연금 신청", "신청처를 확인해 주세요.")

    @patch("src.memory.session_manager.save_exchange")
    @patch("src.memory.session_manager.load_history", return_value=[{"role": "user", "content": "서울에 살아요"}])
    def test_same_session_loads_history(self, load, save):
        sid = "a7057d35-126a-4ebe-b73a-e1ef3f2fb070"
        def run(state):
            self.assertEqual(state["session_id"], sid)
            self.assertEqual(state["history"][0]["content"], "서울에 살아요")
            return {"answer": "네.", "answer_status": "success", "safety_status": "normal"}
        result = run_chat_session("그럼 어디서 신청해요?", sid, run)
        self.assertEqual(result["session_id"], sid)
        load.assert_called_once_with(sid, max_messages=8)

    @patch("src.memory.session_manager.save_exchange")
    @patch("src.memory.session_manager.load_history", return_value=[])
    def test_urgent_not_persisted(self, load, save):
        result = run_chat_session("죽고 싶어요", None, lambda s: {"answer": "안전하게 도움을 요청해 주세요.", "answer_status": "safety_response", "safety_status": "urgent"})
        self.assertEqual(result["safety_status"], "urgent")
        save.assert_not_called()

    @patch("src.memory.session_manager.save_exchange")
    @patch("src.memory.session_manager.load_history", return_value=[])
    def test_llm_error_not_persisted(self, load, save):
        run_chat_session("문의", None, lambda s: {"answer": "오류", "answer_status": "error", "safety_status": "normal"})
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
