"""Application settings, read from environment variables or the project-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # a blank `KEY=` line means "not set", not an empty string
    )

    # AI providers
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None

    # Search providers
    tavily_api_key: SecretStr | None = None
    exa_api_key: SecretStr | None = None
    jina_api_key: SecretStr | None = None
    github_token: SecretStr | None = None

    # Monthly search budgets (free tiers); the app stops calling an engine near its limit
    tavily_monthly_credits: float = 1000.0  # 1 credit per basic search
    exa_monthly_usd: float = 10.0  # free monthly credit; the one-time bonus is extra headroom
    exa_usd_per_search: float = 0.007  # measured 13 Nov 2026 (search without page contents)

    # Storage
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'backend' / 'local.db'}"

    # App
    demo_access_code: SecretStr | None = None
    # Encrypts model API keys that users save in the app. Any long random string; changing it
    # makes saved keys unreadable (they must be entered again).
    settings_secret: SecretStr | None = None
    sec_contact_email: str | None = None
    http_timeout_s: float = 10.0
    user_agent: str = "Lede/0.1 (research prototype)"


@lru_cache
def get_settings() -> Settings:
    return Settings()
