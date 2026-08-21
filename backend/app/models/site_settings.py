from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SiteSettings(Base):
    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    bank_holder: Mapped[str] = mapped_column(String(255), default="AutoPrestige SAS")
    bank_iban: Mapped[str] = mapped_column(String(100), default="FR76 ACCT-000031 2345 678")
    bank_bic: Mapped[str] = mapped_column(String(50), default="BNPAFRPP")
    bank_transfer_type: Mapped[str] = mapped_column(String(100), default="INSTANTANÉ")
    contact_phone: Mapped[str] = mapped_column(String(50), default="+33 1 42 86 82 00")
    contact_email: Mapped[str] = mapped_column(String(255), default="contact@autoprestige.fr")
    contact_whatsapp: Mapped[str] = mapped_column(String(100), default="33142868200")
    contact_address: Mapped[str] = mapped_column(String(500), default="")
