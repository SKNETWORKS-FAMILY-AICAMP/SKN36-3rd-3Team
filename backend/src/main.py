
from fastapi import FastAPI

from backend.src.api.health import router as health_router
from backend.src.api.sessions import router as session_router
from backend.src.api.chat import router as chat_router

from backend.src.api.ask import router as ask_router
from backend.src.api.policies import router as policies_router
from backend.src.api.location import router as location_router

app = FastAPI(
    title="Welfare RAG Chatbot API",
    version="1.0.0",
)

app.include_router(health_router)
app.include_router(session_router)
app.include_router(chat_router)
app.include_router(ask_router)
app.include_router(policies_router)
app.include_router(location_router)