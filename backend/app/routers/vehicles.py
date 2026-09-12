"""Catalogue public véhicules."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.commerce import Vehicle

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])

# Le catalogue est public et change rarement : on autorise un cache court
# (CDN / navigateur / proxy) pour alléger la charge sur l'API.
CATALOG_CACHE_CONTROL = "public, max-age=300"

# Langues servies pour les descriptions pré-traduites (phase 3 SEO —
# docs/plan-seo-multilingue.md). Hors liste → 422 (validation) ; description
# localisée vide → repli FR garanti (jamais de description vide).
SUPPORTED_LANGS = ("en", "de", "it", "es", "pt", "ro")
LangParam = Annotated[str | None, Query(pattern="^(" + "|".join(SUPPORTED_LANGS) + ")?$")]


def _localized_description(vehicle: Vehicle, lang: str | None) -> str:
    """Description dans la langue demandée, repli FR si non traduite."""
    if not lang:
        return vehicle.description
    return getattr(vehicle, f"description_{lang}") or vehicle.description


def _apply_lang(vehicles: list[Vehicle], lang: str | None) -> None:
    """Écrase le champ `description` du modèle par sa variante localisée.

    VehiclePublic expose toujours `description` → zéro breaking change pour
    les clients existants (le front passe simplement ?lang= quand il veut).
    """
    if not lang:
        return
    for v in vehicles:
        v.description = _localized_description(v, lang)

# Pagination bornée : le catalogue est public — un plafond sur `limit` évite
# qu'un client extraye toute la table (ou pire, force des requêtes géantes).
SkipParam = Annotated[int, Query(ge=0, description="Décalage de pagination")]
LimitParam = Annotated[int, Query(ge=1, le=200, description="Taille de page (max 200)")]


def set_catalog_cache(response: Response):
    response.headers["Cache-Control"] = CATALOG_CACHE_CONTROL


class VehiclePublic(BaseModel):
    id: int
    category: str
    brand: str
    model: str
    year: int
    fuel: str
    transmission: str
    mileage: int
    price: float
    monthly: float
    type: str
    body_category: str
    power: int
    featured: bool
    promo: bool
    image: str
    images: str
    description: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[VehiclePublic])
async def list_public_vehicles(
    response: Response,
    db: AsyncSession = Depends(get_db),
    category: str | None = None,
    q: str | None = None,
    lang: LangParam = None,
    skip: SkipParam = 0,
    limit: LimitParam = 200,
):
    set_catalog_cache(response)
    query = select(Vehicle).where(Vehicle.is_active.is_(True)).order_by(desc(Vehicle.featured), desc(Vehicle.created_at))
    if category:
        query = query.where(Vehicle.category == category)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            (func.lower(Vehicle.brand).like(like))
            | (func.lower(Vehicle.model).like(like))
        )
    result = await db.execute(query.offset(skip).limit(limit))
    vehicles = list(result.scalars().all())
    _apply_lang(vehicles, lang)
    return vehicles


@router.get("/{vehicle_id}", response_model=VehiclePublic)
async def get_vehicle(
    vehicle_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
    lang: LangParam = None,
):
    set_catalog_cache(response)
    result = await db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.is_active.is_(True))
    )
    v = result.scalars().first()
    if not v:
        from fastapi import HTTPException
        raise HTTPException(404, "Véhicule introuvable")
    _apply_lang([v], lang)
    return v
