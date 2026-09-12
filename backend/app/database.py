from contextlib import suppress

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Pool tuning: keep connections alive, recycle stale ones, ping before use
_engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,       # detect stale connections
    "pool_recycle": 1800,         # recycle connections every 30 min
}

# PostgreSQL-specific pool settings
if settings.DATABASE_URL.startswith("postgresql"):
    _engine_kwargs["pool_size"] = 10     # persistent connections
    _engine_kwargs["max_overflow"] = 20   # extra connections under load
else:
    # SQLite (aiosqlite) utilise NullPool : pool_size n'est pas accepté.
    pass

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass


# Import models after Base exists so every table is registered before startup.
from app.models import commerce, reviews, site_settings, user  # noqa: F401,E402


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=list(Base.metadata.sorted_tables)
            )
        )

        if conn.dialect.name == "sqlite":
            migrations = [
                "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0",
                "ALTER TABLE installments ADD COLUMN payment_status VARCHAR(20) DEFAULT 'unpaid'",
                "ALTER TABLE installments ADD COLUMN claimed_at DATETIME",
                "ALTER TABLE installments ADD COLUMN admin_note TEXT DEFAULT ''",
                "ALTER TABLE otp_codes ADD COLUMN attempts INTEGER DEFAULT 0",
                "ALTER TABLE deliveries ADD COLUMN recipient_first_name VARCHAR(100) DEFAULT ''",
                "ALTER TABLE deliveries ADD COLUMN recipient_last_name VARCHAR(100) DEFAULT ''",
                "ALTER TABLE deliveries ADD COLUMN recipient_phone VARCHAR(30) DEFAULT ''",
                "ALTER TABLE deliveries ADD COLUMN delivery_address TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0",
            ]
            for sql in migrations:
                with suppress(Exception):
                    await conn.execute(text(sql))

        # Index sur les colonnes filtrées/triées du catalogue (idempotents)
        # create_all ne crée pas les index des tables déjà existantes → CREATE INDEX IF NOT EXISTS.
        indexes = [
            # Requête catalogue principale : WHERE is_active ORDER BY featured DESC, created_at DESC
            "CREATE INDEX IF NOT EXISTS ix_vehicles_active_featured ON vehicles (is_active, featured, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_vehicles_category ON vehicles (category)",
            "CREATE INDEX IF NOT EXISTS ix_vehicles_brand ON vehicles (brand)",
            "CREATE INDEX IF NOT EXISTS ix_orders_status ON orders (status)",
            "CREATE INDEX IF NOT EXISTS ix_installments_payment_status ON installments (payment_status)",
        ]
        for sql in indexes:
            with suppress(Exception):
                await conn.execute(text(sql))

        if conn.dialect.name == "postgresql":
            users_exists = await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')")
            )
            # Migration idempotente : ajoute token_version aux tables existantes
            # (create_all ne modifie pas les tables déjà présentes).
            has_token_version = await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'token_version')")
            )
            if not has_token_version:
                await conn.execute(
                    text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
                )
        else:
            users_exists = await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users')")
            )
        if not users_exists:
            raise RuntimeError("Database schema initialization failed: users table was not created.")

    # Créer / synchroniser le compte admin depuis l'environnement
    async with AsyncSessionLocal() as db:
        await _bootstrap_admin(db)


async def _bootstrap_admin(db: AsyncSession) -> None:
    """Crée ou synchronise le compte admin depuis l'environnement.

    La source de vérité est ADMIN_PASSWORD / ADMIN_EMAIL (variables Render).
    À CHAQUE démarrage : si un mot de passe admin est défini et qu'il diffère
    de celui stocké (ou que le compte n'existe pas), le hash est (ré)écrit.
    Sans cela, changer ADMIN_PASSWORD sur Render ne mettrait jamais à jour un
    compte admin déjà créé lors d'un déploiement précédent.
    """
    from app.models.user import User
    from app.services.auth import get_user_by_email, hash_password, verify_password

    if not settings.ADMIN_PASSWORD or not settings.ADMIN_EMAIL:
        return

    admin = await get_user_by_email(db, settings.ADMIN_EMAIL)
    if admin is None:
        admin = User(
            first_name="Admin",
            last_name="Autohaus",
            email=settings.ADMIN_EMAIL.lower(),
            phone="",
            monthly_salary=0,
            hashed_password=hash_password(settings.ADMIN_PASSWORD),
            is_verified=True,
            is_active=True,
            is_admin=True,
            registration_step=4,
        )
        db.add(admin)
        await db.commit()
        print("Admin créé : " + settings.ADMIN_EMAIL)
        return

    password_changed = not admin.hashed_password or not verify_password(
        settings.ADMIN_PASSWORD, admin.hashed_password
    )
    needs_sync = (
        password_changed
        or not admin.is_admin
        or not admin.is_verified
        or not admin.is_active
    )
    if not needs_sync:
        return

    if password_changed:
        admin.hashed_password = hash_password(settings.ADMIN_PASSWORD)
    admin.is_admin = True
    admin.is_verified = True
    admin.is_active = True
    await db.commit()
    print("Compte admin synchronisé avec l'environnement : " + settings.ADMIN_EMAIL)
