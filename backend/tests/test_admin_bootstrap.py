import pytest

from app.models.user import User
from app.services.auth import get_user_by_email, hash_password, verify_password


@pytest.fixture(autouse=True)
async def _admin_settings(db_session):
    from app.config import settings

    saved_email = settings.ADMIN_EMAIL
    saved_password = settings.ADMIN_PASSWORD
    yield
    settings.ADMIN_EMAIL = saved_email
    settings.ADMIN_PASSWORD = saved_password


async def test_bootstrap_creates_admin(db_session):
    from app.config import settings
    from app.database import _bootstrap_admin

    settings.ADMIN_EMAIL = "test-bootstrap@autoprestige.fr"
    settings.ADMIN_PASSWORD = "BootstrapPass123!"

    await _bootstrap_admin(db_session)

    admin = await get_user_by_email(db_session, settings.ADMIN_EMAIL)
    assert admin is not None
    assert admin.is_admin and admin.is_verified and admin.is_active
    assert admin.registration_step == 4
    assert verify_password("BootstrapPass123!", admin.hashed_password)


async def test_bootstrap_syncs_changed_password(db_session):
    from app.config import settings
    from app.database import _bootstrap_admin

    db_session.add(
        User(
            first_name="Admin",
            last_name="Autohaus",
            email="test-sync@autoprestige.fr",
            phone="",
            monthly_salary=0,
            hashed_password=hash_password("OldPassword123!"),
            is_verified=True,
            is_active=True,
            is_admin=True,
            registration_step=4,
        )
    )
    await db_session.commit()

    settings.ADMIN_EMAIL = "test-sync@autoprestige.fr"
    settings.ADMIN_PASSWORD = "NewPassword456!"

    await _bootstrap_admin(db_session)

    admin = await get_user_by_email(db_session, settings.ADMIN_EMAIL)
    assert admin is not None
    # Le nouveau mot de passe de l'environnement est bien appliqué à chaque boot.
    assert verify_password("NewPassword456!", admin.hashed_password)
    assert not verify_password("OldPassword123!", admin.hashed_password)


async def test_bootstrap_noop_without_password(db_session):
    from app.config import settings
    from app.database import _bootstrap_admin

    db_session.add(
        User(
            first_name="Admin",
            last_name="Autohaus",
            email="test-noop@autoprestige.fr",
            phone="",
            monthly_salary=0,
            hashed_password=hash_password("KeepPassword123!"),
            is_verified=True,
            is_active=True,
            is_admin=True,
            registration_step=4,
        )
    )
    await db_session.commit()

    settings.ADMIN_EMAIL = "test-noop@autoprestige.fr"
    settings.ADMIN_PASSWORD = ""

    await _bootstrap_admin(db_session)

    admin = await get_user_by_email(db_session, settings.ADMIN_EMAIL)
    assert admin is not None
    assert verify_password("KeepPassword123!", admin.hashed_password)
