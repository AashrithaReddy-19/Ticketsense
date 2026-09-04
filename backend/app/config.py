from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[2] is the repo root, where the shared .env lives.
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ROOT_ENV, env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://ticketsense:ticketsense@localhost:5432/ticketsense"

    app_env: str = "development"
    cors_origins: str = "http://localhost:5173"

    llm_provider: str = "stub"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30
    llm_max_retries: int = 2

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachment_max_pdf_pages: int = 25
    attachment_max_extracted_chars: int = 50_000
    attachment_context_chars: int = 8_000
    attachment_max_image_pixels: int = 25_000_000
    attachment_storage_root: str = "uploads/attachments"
    attachment_extraction_timeout_seconds: int = 30

    jwt_secret_key: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    refresh_expire_days: int = 14
    cookie_secure: bool = False
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    session_cleanup_interval_seconds: int = 3600
    # General per-client abuse throttle (not the account-specific login lockout above,
    # which remains the actual brute-force defense). Keyed by client host, so shared
    # NAT/corporate-proxy traffic and a dashboard's own auto-refresh polling across
    # several open tabs must fit comfortably inside this budget.
    general_rate_limit_requests: int = 600
    general_rate_limit_window_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
