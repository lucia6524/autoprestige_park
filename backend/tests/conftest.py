import os
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 40)
os.environ.setdefault("ADMIN_PASSWORD", "AdminPassword123!")
os.environ.setdefault("BREVO_API_KEY", "")

# StaticPool : une SEULE base en mémoire partagée par toutes les connexions
# par :memory: (sinon chaque connexion a sa propre base vide).
_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _prepare_db():
    import app.database as database_module

    # Pointe app.database vers l'engine de test pour que init_db (exécuté au
    # startup) crée les tables sur l'engine de test et non sur le vrai.
    database_module.engine = _engine
    database_module.AsyncSessionLocal = _TestSessionLocal

    from app.database import init_db

    await init_db()
    yield
    # Purge des tables entre deux tests (isolation).
    from app.models_lib import Base as ModelsBase

    async with _engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys = OFF"))
        for table in reversed(ModelsBase.metadata.sorted_tables):
            await conn.execute(text(f'DELETE FROM "{table.name}"'))
        await conn.execute(text("PRAGMA foreign_keys = ON"))

    # Rate limiters en mémoire (module-level) : on les vide pour ne pas
    # propager les compteurs d'un test à l'autre (même IP).
    import app.routers.auth as auth_router
    from app.services import rate_limit

    auth_router._rate_limits.clear()
    rate_limit._buckets.clear()


@pytest.fixture()
async def db_session(_prepare_db):
    async with _TestSessionLocal() as session:
        yield session


@pytest.fixture()
async def client(_prepare_db):
    from app.database import get_db
    from app.main import app

    async def _override_get_db():
        async with _TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def make_user():
    """Crée directement un utilisateur vérifié en base (sans passer par l'API)."""

    async def _make(
        db,
        email="client-test@autoprestige.fr",
        password="ClientPassword123!",
        is_admin=False,
    ):
        from app.models.user import User
        from app.services.auth import hash_password

        user = User(
            first_name="Client",
            last_name="Test",
            email=email,
            phone="+33123456789",
            monthly_salary=3000,
            hashed_password=hash_password(password) if password else "",
            is_verified=True,
            is_active=True,
            is_admin=is_admin,
            registration_step=4,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    return _make


@pytest.fixture()
async def auth_headers(client, db_session, make_user):
    user = await make_user(db_session)
    resp = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "ClientPassword123!"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return token, user
