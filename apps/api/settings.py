"""Environment settings (secrets from .env) and repo paths."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"
RESEARCH_DIR = ROOT / "research"
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    groq_api_key: str = ""
    gemini_api_key: str = ""
    nvidia_api_key: str = ""
    mistral_api_key: str = ""
    openrouter_api_key: str = ""
    # "api_key" (default) or "oauth": use gcloud Application Default Credentials for Gemini.
    gemini_auth: str = "api_key"
    google_cloud_quota_project: str = ""
    youtube_api_key: str = ""
    courtlistener_token: str = ""
    notion_token: str = ""
    notion_database_id: str = ""
    sec_user_agent: str = ""
    db_path: Path = DATA_DIR / "wyrd.db"

    def key_for(self, env_name: str) -> str:
        """Look up a secret by its env var name (as referenced in providers.yaml)."""
        return str(getattr(self, env_name.lower(), "") or "")


def mask_secret(value: str) -> str:
    """Show only enough of a key to recognise it. Never log or display full keys."""
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}…{value[-4:]}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
