from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, text
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
from app.models import commerce, site_settings, user  # noqa: F401

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
            ]
            for sql in migrations:
                try:
                    await conn.execute(text(sql))
                except Exception:
                    pass

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
            try:
                await conn.execute(text(sql))
            except Exception:
                pass

        if conn.dialect.name == "postgresql":
            users_exists = await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')")
            )
        else:
            users_exists = await conn.scalar(
                text("SELECT EXISTS (SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users')")
            )
        if not users_exists:
            raise RuntimeError("Database schema initialization failed: users table was not created.")

    # Créer le compte admin par défaut s'il n'existe pas
    from app.models.user import User
    from app.services.auth import hash_password, get_user_by_email

    async with AsyncSessionLocal() as db:
        admin = await get_user_by_email(db, settings.ADMIN_EMAIL)
        if not admin:
            if not settings.ADMIN_PASSWORD:
                print("⚠️  ADMIN_PASSWORD non défini — compte admin non créé. Configurez ADMIN_PASSWORD dans vos variables d'environnement.")
            else:
                admin = User(
                    first_name="Admin",
                    last_name="AutoPrestige",
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
                print(f"✅ Admin créé : {settings.ADMIN_EMAIL}")
        elif not admin.is_admin:
            admin.is_admin = True
            admin.is_verified = True
            admin.is_active = True
            if not admin.hashed_password and settings.ADMIN_PASSWORD:
                admin.hashed_password = hash_password(settings.ADMIN_PASSWORD)
            await db.commit()
            print(f"✅ Droits admin accordés à : {settings.ADMIN_EMAIL}")
