import json
import os
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


def normalize_database_url(url: str) -> str:
    """Use the async PostgreSQL driver when Render provides a Postgres URL."""
    if url.startswith("postgres://"):
        return normalize_database_url("postgresql://" + url[len("postgres://"):])
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    else:
        return url

    # Render fournit une URL *externe* du type
    #   postgresql://user:pass@host/db?sslmode=require&...
    # `sslmode` est un paramètre libpq (psycopg2) : asyncpg ne le comprend pas
    # et refuserait l'URL au démarrage. Le TLS étant MANDATOIRE pour une
    # connexion externe, on convertit sslmode=require → ssl=require (asyncpg).
    scheme, _, host_and_query = url.partition("://")
    hostpath, _, query = host_and_query.partition("?")
    if query:
        params = {}
        for pair in query.split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                params[key.lower()] = value
        if "sslmode" in params:
            mode = params.pop("sslmode").lower()
            if mode in ("require", "prefer", "verify-ca", "verify-full", "true", "1"):
                params.setdefault("ssl", "require")
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{scheme}://{hostpath}?{query}"
        else:
            url = f"{scheme}://{hostpath}"
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
    APP_NAME: str = "Autohaus API"
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
    # --- Traduction automatique (dynamique) ---
    # Service gratuit utilisé : endpoint public Google (sans clé). Les champs
    # ci-dessous ne servent qu'à l'API officielle payante (librement réactivable).
    GOOGLE_TRANSLATE_API_KEY: str = ""
    GOOGLE_TRANSLATE_API_URL: str = "https://translation.googleapis.com/language/translate/v2"

    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5          # tentatives max par code
    OTP_MAX_PER_HOUR: int = 5          # codes générés max / email / heure
    OTP_LENGTH: int = 6
    CORS_ORIGINS: str = ""  # Empty = localhost only in dev, must be set in production

    # Admin account (created at startup if absent)
    # AUCUNE valeur par défaut : l'email et le mot de passe de l'administrateur
    # doivent être fournis par l'environnement (variables Render), jamais
    # codés dans le dépôt (un identifiant public ferait de l'admin une cible).
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""

    class Config:
        env_file = str(BASE_DIR / ".env")
        extra = "ignore"

settings = Settings()
settings.DATABASE_URL = normalize_database_url(settings.DATABASE_URL)
parsed_origins = parse_cors_origins(settings.CORS_ORIGINS)
# Origine(s) de production toujours autorisées, même si CORS_ORIGINS n'est
# pas (encore) renseigné dans l'environnement Render — évite de bloquer les
# appels du site (ex. /site-settings) quand l'env var est absente ou partielle.
PROD_DEFAULT_ORIGINS = [
    "https://autohaus-park.onrender.com",
]
if parsed_origins:
    settings.CORS_ORIGINS = list(parsed_origins)
    if settings.ENVIRONMENT.lower() == "production":
        for origin in PROD_DEFAULT_ORIGINS:
            if origin not in settings.CORS_ORIGINS:
                settings.CORS_ORIGINS.append(origin)
elif settings.ENVIRONMENT.lower() != "production":
    # Development: allow localhost
    settings.CORS_ORIGINS = ["http://localhost:*", "http://127.0.0.1:*"]
else:
    settings.CORS_ORIGINS = list(PROD_DEFAULT_ORIGINS)

if settings.ENVIRONMENT.lower() == "production":
    if len(settings.SECRET_KEY) < 32:
        raise RuntimeError("SECRET_KEY must be set via environment variable and be at least 32 characters in production.")
    # Une clé auto-générée (défaut secrets.token_urlsafe) passerait le check
    # de longueur ci-dessus mais régénère une clé NOUVELLE à chaque démarrage :
    # tous les JWT/OTP hashes sont alors invalidés à chaque redeploy. Il faut
    # donc qu'elle soit explicitement fournie dans l'environnement en prod.
    if not os.environ.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY must be defined as an environment variable in production "
            "(not auto-generated): otherwise sessions reset on every deploy."
        )
    if not settings.ADMIN_PASSWORD or len(settings.ADMIN_PASSWORD) < 12:
        raise RuntimeError("ADMIN_PASSWORD must be set via environment variable and be at least 12 characters in production.")
    if not settings.ADMIN_EMAIL:
        raise RuntimeError("ADMIN_EMAIL must be set via environment variable in production (no default admin account).")
    if settings.CORS_ORIGINS == ["*"] or not settings.CORS_ORIGINS:
        raise RuntimeError("CORS_ORIGINS must explicitly list the frontend origins in production.")
