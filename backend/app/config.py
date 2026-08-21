import os
from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    APP_NAME: str = "AutoPrestige API"
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

    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5          # tentatives max par code
    OTP_MAX_PER_HOUR: int = 5          # codes générés max / email / heure
    OTP_LENGTH: int = 6
    CORS_ORIGINS: list[str] = ["*"]

    # Admin par défaut (créé au démarrage si absent)
    ADMIN_EMAIL: str = "admin@autoprestige.fr"
    ADMIN_PASSWORD: str = "Admin@Prestige2026"

    class Config:
        env_file = str(BASE_DIR / ".env")
        extra = "ignore"

settings = Settings()
