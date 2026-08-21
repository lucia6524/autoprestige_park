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


class SiteSettingsOut(BaseModel):
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
    result = await db.execute(select(SiteSettings).where(SiteSettings.id == 1))
    settings = result.scalars().first()
    if settings:
        return settings
    settings = SiteSettings(id=1, **DEFAULT_SETTINGS)
    db.add(settings)
    await db.commit()
    await db.refresh(settings)
    return settings


@router.get("", response_model=SiteSettingsOut)
async def read_site_settings(db: AsyncSession = Depends(get_db)):
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
    return settings
