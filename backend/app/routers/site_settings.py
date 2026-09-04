import time
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_admin
from app.models.site_settings import SiteSettings
from app.models.user import User

router = APIRouter(prefix="/site-settings", tags=["Site settings"])

# Simple in-memory cache for site settings (single-row, rarely changes)
_settings_cache: Optional[dict] = None
_settings_cache_ts: float = 0
_CACHE_TTL = 300  # 5 minutes


def _invalidate_settings_cache():
    global _settings_cache, _settings_cache_ts
    _settings_cache = None
    _settings_cache_ts = 0


class SiteSettingsPublic(BaseModel):
    """Public view — no bank details exposed."""
    contact_phone: str
    contact_email: str
    contact_whatsapp: str
    contact_address: str

    class Config:
        from_attributes = True


class SiteSettingsOut(BaseModel):
    """Admin view — includes bank details."""
    bank_holder: str
    bank_iban: str
    bank_bic: str
    bank_transfer_type: str
    contact_phone: str
    contact_email: str
    contact_whatsapp: str
    contact_address: str

    class Config:
        from_attributes = True


class SiteSettingsUpdate(BaseModel):
    bank_holder: str = Field(default="", max_length=255)
    bank_iban: str = Field(default="", max_length=100)
    bank_bic: str = Field(default="", max_length=50)
    bank_transfer_type: str = Field(default="", max_length=100)
    contact_phone: str = Field(default="", max_length=50)
    contact_email: str = Field(default="", max_length=255)
    contact_whatsapp: str = Field(default="", max_length=100)
    contact_address: str = Field(default="", max_length=500)


DEFAULT_SETTINGS = {
    "bank_holder": "AutoPrestige SAS",
    "bank_iban": "FR76 ACCT-000031 2345 678",
    "bank_bic": "BNPAFRPP",
    "bank_transfer_type": "INSTANTANÉ",
    "contact_phone": "+33 1 42 86 82 00",
    "contact_email": "contact@autoprestige.fr",
    "contact_whatsapp": "33142868200",
    "contact_address": "",
}


async def get_or_create_settings(db: AsyncSession) -> SiteSettings:
    global _settings_cache, _settings_cache_ts

    # Return from cache if fresh
    now = time.time()
    if _settings_cache and (now - _settings_cache_ts) < _CACHE_TTL:
        # Reconstruct object from cache for non-mutating reads
        obj = SiteSettings(id=1, **_settings_cache)
        return obj

    result = await db.execute(select(SiteSettings).where(SiteSettings.id == 1))
    settings = result.scalars().first()
    if not settings:
        settings = SiteSettings(id=1, **DEFAULT_SETTINGS)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    # Populate cache
    _settings_cache = {
        "bank_holder": settings.bank_holder,
        "bank_iban": settings.bank_iban,
        "bank_bic": settings.bank_bic,
        "bank_transfer_type": settings.bank_transfer_type,
        "contact_phone": settings.contact_phone,
        "contact_email": settings.contact_email,
        "contact_whatsapp": settings.contact_whatsapp,
        "contact_address": settings.contact_address,
    }
    _settings_cache_ts = now
    return settings


@router.get("", response_model=SiteSettingsPublic)
async def read_site_settings(db: AsyncSession = Depends(get_db)):
    """Public endpoint — bank details are hidden. Uses cache."""
    settings = await get_or_create_settings(db)
    return SiteSettingsPublic(
        contact_phone=settings.contact_phone,
        contact_email=settings.contact_email,
        contact_whatsapp=settings.contact_whatsapp,
        contact_address=settings.contact_address,
    )


@router.get("/admin", response_model=SiteSettingsOut)
async def read_site_settings_admin(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin endpoint — full settings including bank details."""
    return await get_or_create_settings(db)


@router.put("", response_model=SiteSettingsOut)
async def update_site_settings(
    data: SiteSettingsUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    settings = await get_or_create_settings(db)
    for field, value in data.model_dump().items():
        setattr(settings, field, value.strip())
    await db.commit()
    await db.refresh(settings)
    _invalidate_settings_cache()
    return settings
