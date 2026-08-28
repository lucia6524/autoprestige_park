import os
import json
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
    SECRET_KEY: str = "autoprestige-change-me-in-production-2026-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'autoprestige.db'}"

    # Email (SMTP)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@autoprestige.fr"
    CONTACT_RECIPIENT_EMAIL: str = "contact@autoprestige.fr"
    DEEPL_API_KEY: str = ""
    DEEPL_API_URL: str = "https://api-free.deepl.com/v2/translate"

    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5          # tentatives max par code
    OTP_MAX_PER_HOUR: int = 5          # codes générés max / email / heure
    OTP_LENGTH: int = 6
    CORS_ORIGINS: str = "*"

    # Admin par défaut (créé au démarrage si absent)
    ADMIN_EMAIL: str = "admin@autoprestige.fr"
    ADMIN_PASSWORD: str = "Admin@Prestige2026"

    class Config:
        env_file = str(BASE_DIR / ".env")
        extra = "ignore"

settings = Settings()
settings.DATABASE_URL = normalize_database_url(settings.DATABASE_URL)
settings.CORS_ORIGINS = parse_cors_origins(settings.CORS_ORIGINS)

if settings.ENVIRONMENT.lower() == "production":
    default_secret = "autoprestige-change-me-in-production-2026-secret-key"
    default_password = "Admin@Prestige2026"
    if settings.SECRET_KEY == default_secret or len(settings.SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY must be a unique value of at least 32 characters in production.")
    if settings.ADMIN_PASSWORD == default_password or len(settings.ADMIN_PASSWORD) < 12:
        raise RuntimeError("ADMIN_PASSWORD must be changed and at least 12 characters in production.")
    if settings.CORS_ORIGINS == ["*"] or not settings.CORS_ORIGINS:
        raise RuntimeError("CORS_ORIGINS must explicitly list the frontend origins in production.")
