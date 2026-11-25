from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
load_dotenv(ROOT_DIR / "backend" / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _path(name: str, default: Path) -> Path:
    raw = _env(name)
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(slots=True)
class Settings:
    data_dir: Path
    frontend_dist: Path
    db_path: Path
    mock_state_path: Path
    seed_path: Path
    timezone: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    google_token_path: Path
    aws_region: str
    bedrock_model_id: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_tts_model: str
    elevenlabs_stt_model: str
    allowed_origins: tuple[str, ...]
    backend_url: str

    # --- real integrations -------------------------------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_whisper_model: str = "whisper-large-v3"
    edge_tts_enabled: bool = False
    edge_tts_voice_en: str = "en-IN-NeerjaNeural"
    edge_tts_voice_hi: str = "hi-IN-SwaraNeural"

    # --- security / deployment --------------------------------------------
    owner_password: str = ""
    owner_token: str = ""
    companion_token: str = ""
    extension_token: str = ""
    encryption_key: str = ""
    llm_sync_budget: int = 20
    background_sync: bool = False
    sync_interval_minutes: int = 10
    retention_days: int = 180
    public_base_url: str = ""
    demo_enabled: bool = True

    @classmethod
    def load(cls) -> "Settings":
        data_dir = _path("SPARK_DATA_DIR", ROOT_DIR / "data")
        token_override = _env("SPARK_GOOGLE_TOKEN_PATH") or _env("GOOGLE_TOKEN_PATH")
        google_token_path = (
            Path(token_override).expanduser().resolve()
            if token_override
            else data_dir / "google_token.json"
        )
        return cls(
            data_dir=data_dir,
            frontend_dist=_path("SPARK_FRONTEND_DIST", ROOT_DIR / "frontend" / "dist"),
            db_path=_path("SPARK_DB_PATH", data_dir / "spark.db"),
            mock_state_path=_path("SPARK_MOCK_STATE", data_dir / "mock_workspace.json"),
            seed_path=_path(
                "SPARK_SEED", ROOT_DIR / "backend" / "app" / "seed" / "workspace.json"
            ),
            timezone=_env("SPARK_TIMEZONE", "Asia/Kolkata"),
            google_client_id=_env("GOOGLE_CLIENT_ID"),
            google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
            google_redirect_uri=_env(
                "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback"
            ),
            google_token_path=google_token_path,
            aws_region=_env("AWS_REGION", _env("AWS_DEFAULT_REGION", "us-east-1")),
            bedrock_model_id=_env("BEDROCK_MODEL_ID"),
            elevenlabs_api_key=_env("ELEVENLABS_API_KEY"),
            elevenlabs_voice_id=_env("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
            elevenlabs_tts_model=_env("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2"),
            elevenlabs_stt_model=_env("ELEVENLABS_STT_MODEL", "scribe_v1"),
            allowed_origins=tuple(
                origin.strip()
                for origin in _env(
                    "SPARK_ALLOWED_ORIGINS",
                    "http://localhost:5173,http://127.0.0.1:5173",
                ).split(",")
                if origin.strip()
            ),
            backend_url=_env("SPARK_BACKEND_URL", "http://localhost:8000"),
            gemini_api_key=_env("GEMINI_API_KEY"),
            gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
            groq_api_key=_env("GROQ_API_KEY"),
            groq_model=_env("GROQ_MODEL", "llama-3.3-70b-versatile"),
            groq_whisper_model=_env("GROQ_WHISPER_MODEL", "whisper-large-v3"),
            edge_tts_enabled=_bool_env("SPARK_EDGE_TTS", False),
            edge_tts_voice_en=_env("EDGE_TTS_VOICE_EN", "en-IN-NeerjaNeural"),
            edge_tts_voice_hi=_env("EDGE_TTS_VOICE_HI", "hi-IN-SwaraNeural"),
            owner_password=_env("SPARK_OWNER_PASSWORD"),
            owner_token=_env("SPARK_OWNER_TOKEN"),
            companion_token=_env("SPARK_COMPANION_TOKEN"),
            extension_token=_env("SPARK_EXTENSION_TOKEN"),
            encryption_key=_env("SPARK_ENCRYPTION_KEY"),
            background_sync=_bool_env("SPARK_BACKGROUND_SYNC", False),
            llm_sync_budget=_int_env("SPARK_LLM_SYNC_BUDGET", 20),
            sync_interval_minutes=_int_env("SPARK_SYNC_INTERVAL_MINUTES", 10),
            retention_days=_int_env("SPARK_RETENTION_DAYS", 180),
            public_base_url=_env("SPARK_PUBLIC_BASE_URL"),
            demo_enabled=_bool_env("SPARK_DEMO_ENABLED", True),
        )

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_connected(self) -> bool:
        return self.google_configured and self.google_token_path.exists()

    @property
    def llm_provider(self) -> str:
        if self.gemini_api_key:
            return "gemini"
        if self.groq_api_key:
            return "groq"
        if self.bedrock_model_id:
            return "bedrock"
        return "local-planner"

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider != "local-planner"

    @property
    def voice_provider(self) -> str:
        if self.elevenlabs_api_key:
            return "elevenlabs"
        if self.edge_tts_enabled:
            return "edge-tts"
        return "browser"

    @property
    def voice_configured(self) -> bool:
        return self.voice_provider in {"elevenlabs", "edge-tts"}

    @property
    def mode(self) -> str:
        return "live" if self.google_connected else "demo"

    def capabilities(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "google_configured": self.google_configured,
            "google_connected": self.google_connected,
            "calendar": "google" if self.google_connected else "demo",
            "gmail": "google" if self.google_connected else "demo",
            "drive": "google" if self.google_connected else "demo",
            "llm": self.llm_provider,
            "voice": self.voice_provider,
            "approval_gate": True,
            "audit_log": True,
            "unified_inbox": True,
            "deadlines": True,
            "reminders": True,
            "companion": bool(self.companion_token or self.owner_token),
            "forms": True,
            "background_sync": self.background_sync,
            "auth": bool(self.owner_password or self.owner_token),
        }

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.google_token_path.parent.mkdir(parents=True, exist_ok=True)
        self.mock_state_path.parent.mkdir(parents=True, exist_ok=True)
