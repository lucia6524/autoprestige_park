"""Environnement Alembic asynchrone.

Construit le moteur sur DATABASE_URL (config de l'app) et découvre le schéma
via app.models_lib — aucun moteur n'est créé à l'import, ce qui permet de
l'exécuter dans l'environnement (y compris en production sans briser les
gardes de config.py).
"""
import os

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

# Charge la config applicative (env vars .env) pour retrouver DATABASE_URL.
os.environ.setdefault("ENVIRONMENT", "development")
from app.config import settings  # noqa: E402
from app.models_lib import Base  # noqa: E402

target_metadata = Base.metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    """Migrations « offline » : génère le SQL sans connexion."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()