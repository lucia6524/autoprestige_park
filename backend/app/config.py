import os
import json
import secrets
from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def normalize_database_url(url: str) -> str:
    """Use the async PostgreSQL driver when Render provides a Postgres URL."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


def parse_cors_origins(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [origin.strip() for origin in parsed if isinstance(origin, str) and origin.strip()]
    except json.JSONDecodeError:
        pass
    return [origin.strip() for origin in value.split(",") if origin.strip()]

class Settings(BaseSettings):
    APP_NAME: str = "AutoPrestige API"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = secrets.token_urlsafe(48)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour (reduced from 7 days for security)
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'autoprestige.db'}"

    # Email (SMTP)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@autoprestige.fr"
    CONTACT_RECIPIENT_EMAIL: str = "contact@autoprestige.fr"
    BREVO_API_KEY: str = ""
    DEEPL_API_KEY: str = ""
    DEEPL_API_URL: str = "https://api-free.deepl.com/v2/translate"

    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5          # tentatives max par code
    OTP_MAX_PER_HOUR: int = 5          # codes générés max / email / heure
    OTP_LENGTH: int = 6
    CORS_ORIGINS: str = ""  # Empty = localhost only in dev, must be set in production

    # Admin account (created at startup if absent)
    ADMIN_EMAIL: str = "admin@autoprestige.fr"
    ADMIN_PASSWORD: str = ""

    class Config:
        env_file = str(BASE_DIR / ".env")
        extra = "ignore"

settings = Settings()
settings.DATABASE_URL = normalize_database_url(settings.DATABASE_URL)
parsed_origins = parse_cors_origins(settings.CORS_ORIGINS)
if parsed_origins:
    settings.CORS_ORIGINS = parsed_origins
elif settings.ENVIRONMENT.lower() != "production":
    # Development: allow localhost
    settings.CORS_ORIGINS = ["http://localhost:*", "http://127.0.0.1:*"]
else:
    settings.CORS_ORIGINS = []

if settings.ENVIRONMENT.lower() == "production":
    if len(settings.SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY must be set via environment variable and be at least 32 characters in production.")
    if not settings.ADMIN_PASSWORD or len(settings.ADMIN_PASSWORD) < 12:
        raise RuntimeError("ADMIN_PASSWORD must be set via environment variable and be at least 12 characters in production.")
    if settings.CORS_ORIGINS == ["*"] or not settings.CORS_ORIGINS:
        raise RuntimeError("CORS_ORIGINS must explicitly list the frontend origins in production.")
