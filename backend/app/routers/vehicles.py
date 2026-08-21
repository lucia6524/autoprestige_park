"""Catalogue public véhicules."""
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.models.commerce import Vehicle

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


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


@router.get("", response_model=List[VehiclePublic])
async def list_public_vehicles(
    db: AsyncSession = Depends(get_db),
    category: Optional[str] = None,
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
):
    query = select(Vehicle).where(Vehicle.is_active == True).order_by(desc(Vehicle.featured), desc(Vehicle.created_at))
    if category:
        query = query.where(Vehicle.category == category)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            (func.lower(Vehicle.brand).like(like))
            | (func.lower(Vehicle.model).like(like))
        )
    result = await db.execute(query.offset(skip).limit(limit))
    return list(result.scalars().all())


@router.get("/{vehicle_id}", response_model=VehiclePublic)
async def get_vehicle(vehicle_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.is_active == True)
    )
    v = result.scalars().first()
    if not v:
        from fastapi import HTTPException
        raise HTTPException(404, "Véhicule introuvable")
    return v
