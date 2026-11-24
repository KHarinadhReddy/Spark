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

    @classmethod
    def load(cls) -> "Settings":
        data_dir = _path("SPARK_DATA_DIR", ROOT_DIR / "data")
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
            google_token_path=_path(
                "GOOGLE_TOKEN_PATH", data_dir / "google_token.json"
            ),
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
        )

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_connected(self) -> bool:
        return self.google_configured and self.google_token_path.exists()

    @property
    def llm_configured(self) -> bool:
        return bool(self.bedrock_model_id)

    @property
    def voice_configured(self) -> bool:
        return bool(self.elevenlabs_api_key)

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
            "llm": "bedrock-claude" if self.llm_configured else "local-planner",
            "voice": "elevenlabs" if self.voice_configured else "browser",
            "approval_gate": True,
            "audit_log": True,
        }

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.google_token_path.parent.mkdir(parents=True, exist_ok=True)
        self.mock_state_path.parent.mkdir(parents=True, exist_ok=True)
