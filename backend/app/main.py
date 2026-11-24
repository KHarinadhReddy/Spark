from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from .agent.spark import SparkAgent
from .config import Settings
from .core.approval import (
    Action,
    ActionExecutionError,
    ActionNotFound,
    ActionStateError,
    ApprovalGate,
)
from .core.audit import AuditLog
from .core.db import Database
from .mcp.google_workspace import GoogleAuthError, GoogleTokenStore, GoogleWorkspace
from .mcp.mock_workspace import MockWorkspace
from .mcp.tools import build_registry
from .voice import ElevenLabsVoice, VoiceError, VoiceNotConfigured

Language = Literal["en", "hi"]


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language: Language | None = None


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=2500)
    language: Language = "en"


class DeadlineAddIn(BaseModel):
    language: Language = "en"


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()
        self.db = Database(settings.db_path)
        self.db.init()
        self.audit = AuditLog(self.db)
        self.mock = MockWorkspace(settings.mock_state_path, settings.seed_path)
        self.tokens = GoogleTokenStore(
            settings.google_token_path,
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_redirect_uri,
        )
        self.voice = ElevenLabsVoice(settings)
        self.workspace: Any = self.mock
        self.registry = build_registry(self.workspace)
        self.gate = ApprovalGate(self.db, self.registry, self.audit)
        self.agent = SparkAgent(
            settings, self.registry, self.gate, self.workspace, self.audit
        )
        if self.tokens.connected:
            self._activate_google()

    def _activate_google(self) -> None:
        self.gate.expire_pending("switched to live Google workspace")
        self.workspace = GoogleWorkspace(self.tokens)
        self.registry = build_registry(self.workspace)
        self.gate = ApprovalGate(self.db, self.registry, self.audit)
        self.agent = SparkAgent(
            self.settings, self.registry, self.gate, self.workspace, self.audit
        )

    def refresh_workspace(self) -> None:
        if self.tokens.connected:
            self._activate_google()
        else:
            self.gate.expire_pending("switched to demo workspace")
            self.workspace = self.mock
            self.registry = build_registry(self.workspace)
            self.gate = ApprovalGate(self.db, self.registry, self.audit)
            self.agent = SparkAgent(
                self.settings, self.registry, self.gate, self.workspace, self.audit
            )


def _decision_message(action: Action, decision: str) -> tuple[str, str]:
    title = action.preview.get("title", action.tool)
    if decision == "approved":
        return (
            f"Approved — “{title}” is done. The action is in your activity log and can be undone.",
            f"स्वीकृत — “{title}” पूरा हुआ। यह गतिविधि लॉग में है और इसे पूर्ववत किया जा सकता है।",
        )
    if decision == "rejected":
        return (
            f"Dismissed — “{title}” was not executed. No changes were made.",
            f"खारिज — “{title}” लागू नहीं हुआ। कोई बदलाव नहीं हुआ।",
        )
    return (
        f"Undone — “{title}” was reversed and removed.",
        f"पूर्ववत — “{title}” को हटा दिया गया।",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    container = Container(settings)

    app = FastAPI(
        title="Spark",
        version="1.0.0",
        description=(
            "Voice-first MCP agent for student life admin. Reads Calendar, Gmail and Drive; "
            "every write is approval-gated, audited and undoable."
        ),
    )
    app.state.ctx = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ----------------------------------------------------------------- health
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": "Spark",
            "mode": settings.mode,
            "capabilities": settings.capabilities(),
            "pending_actions": len(container.gate.pending()),
            "profile": container.agent.profile,
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "app": "Spark",
            "tagline": "Reads freely. Writes only after you approve.",
            "capabilities": settings.capabilities(),
            "profile": container.agent.profile,
            "google": {
                "configured": settings.google_configured,
                "connected": settings.google_connected,
                "start_url": "/api/auth/google/start",
            },
            "prompts": [
                "Give me my morning brief",
                "Find deadlines in my emails",
                "What's due this week?",
                "What's on my calendar today?",
                "Draft a reminder to the accounts office about the fee",
                "Add a study block on 29 Nov at 3 PM",
                "Find my wHACKiest checklist",
            ],
            "tools": container.registry.catalog(),
        }

    @app.get("/api/tools")
    def tools() -> dict[str, Any]:
        return {"tools": container.registry.catalog()}

    # ------------------------------------------------------------------ agent
    @app.post("/api/chat")
    def chat(payload: ChatIn) -> dict[str, Any]:
        try:
            result = container.agent.handle(payload.message, payload.language)
            return result.public()
        except Exception as exc:
            container.audit.log("agent.error", detail={"error": str(exc)[:300]})
            raise HTTPException(
                status_code=500,
                detail="Spark hit a snag handling that request. Please try again.",
            ) from exc

    @app.get("/api/brief")
    def brief(language: Language = "en") -> dict[str, Any]:
        return container.agent.brief(language)

    @app.get("/api/deadlines")
    def deadlines(language: Language = "en") -> dict[str, Any]:
        from .agent.deadlines import find_deadlines

        found = find_deadlines(container.workspace, container.agent.now())
        return {
            "language": language,
            "count": len(found),
            "deadlines": [deadline.public() for deadline in found],
            "pending_cards": [action.public() for action in container.gate.pending()],
        }

    @app.post("/api/deadlines/{email_id}/add")
    def add_deadline(
        email_id: str, payload: DeadlineAddIn | None = None
    ) -> dict[str, Any]:
        language = payload.language if payload else "en"
        try:
            action, reply = container.agent.add_deadline_to_calendar(email_id, language)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="No upcoming deadline for that email") from exc
        return {"action": action, "reply": reply, "language": language}

    # -------------------------------------------------------- approval + undo
    @app.get("/api/actions")
    def actions(limit: int = 30) -> dict[str, Any]:
        return {
            "pending": [action.public() for action in container.gate.pending()],
            "recent": [action.public() for action in container.gate.recent(limit)],
        }

    @app.get("/api/actions/{action_id}")
    def action_detail(action_id: str) -> dict[str, Any]:
        try:
            return container.gate.get(action_id).public()
        except ActionNotFound as exc:
            raise HTTPException(status_code=404, detail="Action not found") from exc

    def _handle_action(action_id: str, decision: str) -> dict[str, Any]:
        try:
            if decision == "approve":
                action = container.gate.approve(action_id)
            elif decision == "reject":
                action = container.gate.reject(action_id)
            else:
                action = container.gate.undo(action_id)
        except ActionNotFound as exc:
            raise HTTPException(status_code=404, detail="Action not found") from exc
        except ActionStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ActionExecutionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        english, hindi = _decision_message(action, decision)
        return {
            "action": action.public(),
            "message": english,
            "message_hi": hindi,
            "pending": [item.public() for item in container.gate.pending()],
        }

    @app.post("/api/actions/{action_id}/approve")
    def approve(action_id: str) -> dict[str, Any]:
        return _handle_action(action_id, "approve")

    @app.post("/api/actions/{action_id}/reject")
    def reject(action_id: str) -> dict[str, Any]:
        return _handle_action(action_id, "reject")

    @app.post("/api/actions/{action_id}/undo")
    def undo(action_id: str) -> dict[str, Any]:
        return _handle_action(action_id, "undo")

    @app.get("/api/audit")
    def audit(limit: int = 100) -> dict[str, Any]:
        return {"audit": container.audit.list(limit=min(max(limit, 1), 200))}

    # --------------------------------------------------------------- google
    @app.get("/api/auth/google/status")
    def google_status() -> dict[str, Any]:
        return {
            "configured": settings.google_configured,
            "connected": container.tokens.connected,
        }

    @app.get("/api/auth/google/start")
    def google_start() -> Response:
        if not settings.google_configured:
            raise HTTPException(
                status_code=400,
                detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
            )
        state = uuid.uuid4().hex
        return RedirectResponse(container.tokens.authorize_url(state))

    @app.get("/api/auth/google/callback")
    def google_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
        if error:
            return RedirectResponse("/?google=error")
        if not code or not state or not container.tokens.check_state(state):
            raise HTTPException(status_code=400, detail="Invalid OAuth state")
        try:
            container.tokens.exchange(code)
        except GoogleAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        container.refresh_workspace()
        container.audit.log("google.connected", detail={"mode": settings.mode})
        return RedirectResponse("/?google=connected")

    @app.post("/api/auth/google/disconnect")
    def google_disconnect() -> dict[str, Any]:
        container.tokens.disconnect()
        container.refresh_workspace()
        container.audit.log("google.disconnected")
        return {"connected": False, "mode": settings.mode}

    # ------------------------------------------------------------------ voice
    @app.post("/api/voice/tts")
    def tts(payload: TtsIn) -> Response:
        if not container.voice.configured:
            raise HTTPException(
                status_code=503,
                detail="ElevenLabs is not configured; use browser speech synthesis.",
            )
        try:
            audio = container.voice.tts(payload.text, payload.language)
        except VoiceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return Response(content=audio, media_type="audio/mpeg")

    @app.post("/api/voice/stt")
    async def stt(request: Request) -> dict[str, Any]:
        if not container.voice.configured:
            raise HTTPException(
                status_code=503,
                detail="ElevenLabs is not configured; use browser speech recognition.",
            )
        audio = await request.body()
        if not audio:
            raise HTTPException(status_code=400, detail="No audio received")
        content_type = request.headers.get("content-type", "audio/webm")
        try:
            text = container.voice.stt(audio, content_type)
        except (VoiceError, VoiceNotConfigured) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"text": text}

    # ----------------------------------------------------------------- static
    dist = settings.frontend_dist
    if dist.exists() and (dist / "index.html").exists():
        assets = dist / "assets"
        if assets.exists():
            from fastapi.staticfiles import StaticFiles

            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (dist / path).resolve()
            try:
                candidate.relative_to(dist.resolve())
            except ValueError:
                raise HTTPException(status_code=404, detail="Not found") from None
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def root() -> dict[str, Any]:
            return {
                "app": "Spark API",
                "status": "running",
                "ui": "Frontend not built. Run `npm install && npm run build` in frontend/.",
                "docs": "/docs",
            }

    return app


app = create_app()
