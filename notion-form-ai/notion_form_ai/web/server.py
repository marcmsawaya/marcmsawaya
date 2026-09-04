"""FastAPI web chat: `notion-ai-web` then open http://localhost:8377."""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..agent import NotionFormAgent
from ..config import Settings

app = FastAPI(title="Notion Form AI")

_STATIC = Path(__file__).parent / "static"
_settings = Settings()
_sessions: dict[str, NotionFormAgent] = {}
_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ResetRequest(BaseModel):
    session_id: str | None = None


def _session(session_id: str) -> tuple[NotionFormAgent, threading.Lock]:
    with _registry_lock:
        agent = _sessions.get(session_id)
        if agent is None:
            agent = NotionFormAgent(_settings)
            _sessions[session_id] = agent
            _locks[session_id] = threading.Lock()
        return agent, _locks[session_id]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is empty")

    session_id = req.session_id or uuid.uuid4().hex
    agent, lock = _session(session_id)
    events: list[dict] = []

    # Serialize per session: FastAPI runs def endpoints in a threadpool, so two
    # concurrent requests for the same session would otherwise interleave the
    # agent's message history and corrupt it.
    with lock:
        agent.on_event = events.append
        try:
            reply = agent.run(text)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        finally:
            agent.on_event = None

    return {"session_id": session_id, "reply": reply, "events": events}


@app.post("/api/reset")
def reset(req: ResetRequest) -> dict:
    if req.session_id:
        with _registry_lock:
            agent = _sessions.pop(req.session_id, None)
            lock = _locks.pop(req.session_id, None)
        if agent is not None:
            # Wait for any in-flight run on this session before closing.
            if lock is not None:
                with lock:
                    agent.close()
            else:
                agent.close()
    return {"ok": True}


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8377)


if __name__ == "__main__":
    main()
