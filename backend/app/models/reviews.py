"""Témoignages clients (modérés) et demandes de vente avec photos."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.time_utils import utc_now_naive


class Review(Base):
    """Témoignage client soumis depuis la page « Avis clients ».

    Les avis sont créés avec approved=False et ne sont affichés sur le
    site qu'après validation par un administrateur (modération).
    """
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), default="")
    vehicle: Mapped[str] = mapped_column(String(150), default="")  # ex : "BMW Série 3"
    rating: Mapped[int] = mapped_column(Integer, default=5)        # 1..5
    message: Mapped[str] = mapped_column(Text)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)


class SellRequest(Base):
    """Demande d'estimation / reprise envoyée depuis la page « Vendre ».

    Les photos du véhicule sont stockées en data-URL (base64 JPEG compressé
    côté client) dans une chaîne JSON — pas de stockage fichier nécessaire.
    """
    __tablename__ = "sell_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    brand: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(150))
    year: Mapped[int] = mapped_column(Integer, default=0)
    mileage: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    photos: Mapped[str] = mapped_column(Text, default="")  # JSON array de data-URLs
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)  # new | contacted | closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
