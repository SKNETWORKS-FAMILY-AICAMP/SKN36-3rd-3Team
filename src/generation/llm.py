"""LLM adapter. Requires OPENAI_API_KEY and langchain-openai for live answers."""
from __future__ import annotations
import os
from functools import lru_cache

@lru_cache(maxsize=1)
def get_llm():
    from dotenv import load_dotenv
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다. 모의 실행은 --mock 사용.")
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("pip install langchain-openai를 실행하세요.") from exc
    return ChatOpenAI(model=os.getenv("CHAT_MODEL", "gpt-4.1-mini"), temperature=0)


def call_llm(system_text: str, user_text: str) -> str:
    from langchain_core.messages import SystemMessage, HumanMessage
    response = get_llm().invoke([SystemMessage(content=system_text), HumanMessage(content=user_text)])
    if not isinstance(response.content, str):
        raise TypeError("텍스트 LLM 응답이 아닙니다.")
    return response.content.strip()
