from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_db
# Import models so Base.metadata knows them
from app.models import user, commerce  # noqa: F401
from app.models import site_settings as site_settings_model  # noqa: F401
from app.models import reviews as reviews_model  # noqa: F401
from app.routers import auth, cart, orders, admin, vehicles, site_settings, translation, contact, reviews


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("✅ Database initialized")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress responses (JSON payloads with long image URLs compress very well)
app.add_middleware(GZipMiddleware, minimum_size=500)


# ── CSRF defense (Origin validation) ─────────────────────
# L'auth se fait par Bearer token (pas de cookies d'authentification), donc le
# CSRF classique est déjà neutralisé. Ce middleware bloque en plus toute
# requête mutante (POST/PUT/PATCH/DELETE) dont l'Origin ne fait pas partie des
# origines frontend autorisées — empêche un site malveillant de déclencher des
# actions (envoi d'emails payants, inscription, etc.) depuis le navigateur
# d'une victime. Requêtes sans Origin (curl, mobile, server-to-server) : OK.
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _origin_allowed(origin: str) -> bool:
    """Match des origines autorisées, avec support des wildcards de port
    (ex. http://localhost:* utilisés en développement)."""
    from fnmatch import fnmatch

    for allowed in settings.CORS_ORIGINS:
        if allowed == origin:
            return True
        if "*" in allowed and fnmatch(origin, allowed):
            return True
    return False


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin:
            if not _origin_allowed(origin):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Origine non autorisée (protection CSRF)."},
                )
        # Pas d'Origin → client non-navigateur (curl, app mobile) : autorisé.
        # Les navigateurs envoient toujours Origin sur les requêtes mutantes.
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # Skip headers for health checks — lighter load on monitoring probes
    if request.url.path == "/api/health":
        return response
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:;"
    if settings.ENVIRONMENT.lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.include_router(auth.router, prefix="/api")
app.include_router(cart.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(site_settings.router, prefix="/api")
app.include_router(translation.router, prefix="/api")
app.include_router(contact.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
