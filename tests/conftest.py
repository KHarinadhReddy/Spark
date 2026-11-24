from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        frontend_dist=tmp_path / "dist",
        db_path=tmp_path / "spark.db",
        mock_state_path=tmp_path / "mock_workspace.json",
        seed_path=REPO / "backend" / "app" / "seed" / "workspace.json",
        timezone="Asia/Kolkata",
        google_client_id="",
        google_client_secret="",
        google_redirect_uri="http://localhost:8000/api/auth/google/callback",
        google_token_path=tmp_path / "google_token.json",
        aws_region="us-east-1",
        bedrock_model_id="",
        elevenlabs_api_key="",
        elevenlabs_voice_id="test-voice",
        elevenlabs_tts_model="eleven_multilingual_v2",
        elevenlabs_stt_model="scribe_v1",
        allowed_origins=("http://localhost:5173",),
        backend_url="http://localhost:8000",
    )


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture()
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def ctx(app):
    return app.state.ctx
