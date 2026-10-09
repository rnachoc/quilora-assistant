"""HTTP API for the chat widget.

    uvicorn quilora.api.app:app --reload

POST /api/chat          one customer message in, one reply out (session kept server-side)
GET  /api/sessions/{id} the customer-visible transcript (no tool internals)
GET  /healthz           liveness: the process is up
GET  /readyz            readiness: the database answers
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from quilora.agent.loop import Agent
from quilora.agent.session import ConcurrentUpdateError, Conversation, PostgresSessionStore
from quilora.config import Settings, load_settings
from quilora.db import Database

log = logging.getLogger("quilora.api")


class ChatRequest(BaseModel):
    session_id: str | None = Field(default=None, description="Omit to start a conversation.")
    message: str = Field(min_length=1, max_length=4000)


class ToolCallView(BaseModel):
    name: str
    ok: bool
    error_code: str | None
    duration_ms: float


class TurnMeta(BaseModel):
    stop_reason: str
    iterations: int
    latency_ms: float
    cost_usd: float | None
    usage: dict[str, int]
    tools: list[ToolCallView]
    flags: list[str]
    model: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    handed_off: bool
    ticket_id: str | None
    meta: TurnMeta


class TranscriptMessage(BaseModel):
    role: str
    text: str


def visible_transcript(conv: Conversation) -> list[TranscriptMessage]:
    """Only what the customer saw: their messages and the assistant's text, no tool data."""
    out = []
    for m in conv.messages:
        if m["role"] == "user" and isinstance(m["content"], str):
            out.append(TranscriptMessage(role="user", text=m["content"]))
        elif m["role"] == "assistant":
            text = "\n".join(b["text"] for b in m["content"] if b["type"] == "text").strip()
            if text:
                out.append(TranscriptMessage(role="assistant", text=text))
    return out


def create_app(settings: Settings | None = None, agent: Agent | None = None,
               store: Any = None) -> FastAPI:
    settings = settings or load_settings()
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        from quilora.bootstrap import build_agent

        db = agent.db if agent else Database(settings.database_url)
        state["db"] = db
        state["agent"] = agent or build_agent(settings, db=db)
        state["store"] = store or PostgresSessionStore(db)
        yield
        if agent is None:
            db.close()

    app = FastAPI(title="Quilora Assistant API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        try:
            state["db"].ping()
        except Exception as exc:
            raise HTTPException(503, "database unavailable") from exc
        return {"status": "ready"}

    # Sync endpoint on purpose: FastAPI runs it in a worker thread, and the agent, the SDK
    # client and the DB pool are all synchronous. See docs/phases/09-api-widget-docker.md.
    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest) -> ChatResponse:
        sessions = state["store"]
        if request.session_id:
            conv = sessions.load(request.session_id)
            if conv is None:
                raise HTTPException(404, "Unknown session. Start a new conversation.")
        else:
            conv = Conversation(id=str(uuid.uuid4()))

        result = state["agent"].run_turn(conv, request.message)
        try:
            sessions.save(conv)
        except ConcurrentUpdateError as exc:
            raise HTTPException(409, "This conversation was updated by another request. "
                                     "Please resend your message.") from exc

        log.info("turn session=%s stop=%s tools=%s latency_ms=%.0f cost_usd=%s flags=%s",
                 conv.id, result.stop_reason, [c.name for c in result.tool_calls],
                 result.latency_ms, result.cost_usd, result.flags)
        return ChatResponse(
            session_id=conv.id,
            reply=result.reply,
            handed_off=result.handed_off or bool(conv.state.handoff_ticket_id),
            ticket_id=result.ticket_id or conv.state.handoff_ticket_id,
            meta=TurnMeta(
                stop_reason=result.stop_reason, iterations=result.iterations,
                latency_ms=round(result.latency_ms, 1), cost_usd=result.cost_usd,
                usage=result.usage.as_dict(), flags=result.flags, model=result.model,
                tools=[ToolCallView(name=c.name, ok=not c.is_error, error_code=c.error_code,
                                    duration_ms=round(c.duration_ms, 1))
                       for c in result.tool_calls],
            ),
        )

    @app.get("/api/sessions/{session_id}", response_model=list[TranscriptMessage])
    def transcript(session_id: str) -> list[TranscriptMessage]:
        conv = state["store"].load(session_id)
        if conv is None:
            raise HTTPException(404, "Unknown session.")
        return visible_transcript(conv)

    return app


def __getattr__(name: str):
    # `uvicorn quilora.api.app:app` builds the app lazily, so importing this module in tests
    # does not read settings or connect to anything.
    if name == "app":
        logging.basicConfig(level=logging.INFO)
        return create_app()
    raise AttributeError(name)
