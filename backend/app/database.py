from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, text
from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
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
        await conn.run_sync(Base.metadata.create_all)
        # Migrations légères SQLite (ignorer si colonne déjà présente)
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

    # Créer le compte admin par défaut s'il n'existe pas
    from app.models.user import User
    from app.services.auth import hash_password, get_user_by_email

    async with AsyncSessionLocal() as db:
        admin = await get_user_by_email(db, settings.ADMIN_EMAIL)
        if not admin:
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
            if not admin.hashed_password:
                admin.hashed_password = hash_password(settings.ADMIN_PASSWORD)
            await db.commit()
            print(f"✅ Droits admin accordés à : {settings.ADMIN_EMAIL}")
