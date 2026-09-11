"""Témoignages clients (modérés) et demandes de vente avec photos."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_admin
from app.models.reviews import Review, SellRequest
from app.services.email import send_review_email, send_sell_request_email
from app.services.rate_limit import check_rate_limit, get_client_ip

router = APIRouter(tags=["Reviews"])

# Limite de taille du payload photos (JSON base64). 8 Mo couvre largement
# 6 photos compressées côté client (~150-400 Ko chacune).
MAX_PHOTOS_JSON_LENGTH = 8_000_000
# Seules les photos base64 valides sont acceptées : type image annoncé +
# présence d'un payload base64. Bloque data:text/html, data:application/js,
# SVG (data:image/svg+xml peut embarquer du JS) et toute autre charge utile.
import re as _re

_DATA_URL_RE = _re.compile(
    r"^data:image/(?!svg\+xml)(png|jpeg|jpg|gif|webp|avif);base64,[A-Za-z0-9+/=]+$")


# ── Schemas publics ──────────────────────────────────────

class ReviewIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    vehicle: str = Field(default="", max_length=150)
    rating: int = Field(..., ge=1, le=5)
    message: str = Field(..., min_length=5, max_length=3000)


class ReviewOut(BaseModel):
    id: int
    name: str
    vehicle: str
    rating: int
    message: str
    created_at: object

    class Config:
        from_attributes = True


class SellRequestIn(BaseModel):
    brand: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=150)
    year: int = Field(..., ge=1950, le=2030)
    mileage: int = Field(..., ge=0, le=2_000_000)
    name: str = Field(..., min_length=2, max_length=120)
    phone: str = Field(..., min_length=6, max_length=30)
    email: EmailStr
    notes: str = Field(default="", max_length=4000)
    photos: List[str] = Field(default=[], max_length=6)

    @field_validator("photos")
    @classmethod
    def validate_photos(cls, v):
        if not v:
            return v
        clean = []
        for p in v:
            if not isinstance(p, str) or len(p) > 2_000_000 or not _DATA_URL_RE.match(p):
                raise ValueError("Format de photo invalide.")
            clean.append(p)
        return clean


# ── Public : avis approuvés + soumission ─────────────────

@router.get("/reviews", response_model=List[ReviewOut])
async def list_public_reviews(db: AsyncSession = Depends(get_db)):
    """Avis approuvés uniquement (modération)."""
    result = await db.execute(
        select(Review)
        .where(Review.approved == True)
        .order_by(desc(Review.created_at))
        .limit(100)
    )
    return list(result.scalars().all())


@router.get("/reviews/stats")
async def reviews_stats(db: AsyncSession = Depends(get_db)):
    """Note moyenne + nombre d'avis approuvés (pour le bandeau de la page)."""
    result = await db.execute(
        select(func.count(Review.id), func.coalesce(func.avg(Review.rating), 0.0))
        .where(Review.approved == True)
    )
    total, avg = result.one()
    return {"total": int(total), "average": round(float(avg), 1)}


@router.post("/reviews")
async def submit_review(data: ReviewIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Soumission d'un témoignage — enregistré en attente de modération."""
    # Rate limit : 3 avis / 5 min / IP (modération + email payant en aval).
    check_rate_limit("review_submit", get_client_ip(request))

    review = Review(
        name=data.name.strip(),
        email=str(data.email).lower(),
        vehicle=data.vehicle.strip(),
        rating=data.rating,
        message=data.message.strip(),
        approved=False,
    )
    db.add(review)
    await db.commit()

    # Notification email (best effort : ne bloque pas la réponse)
    await send_review_email(review.name, str(data.email), review.vehicle, review.rating, review.message)

    return {"ok": True, "message": "Merci ! Votre avis sera publié après modération."}


# ── Public : demande de vente (reprise) ──────────────────

@router.post("/sell-requests")
async def submit_sell_request(data: SellRequestIn, request: Request, db: AsyncSession = Depends(get_db)):
    """Demande d'estimation avec photos du véhicule."""
    # Rate limit : 3 demandes / 5 min / IP (payload photos lourd + email payant).
    check_rate_limit("sell_request", get_client_ip(request))

    import json

    photos_json = "[]"
    photo_count = 0
    if data.photos:
        # Validation stricte déjà faite par le validator Pydantic (data-URL
        # image base64 uniquement, pas de SVG). Double contrôle de la taille.
        clean = data.photos
        photos_json = json.dumps(clean)
        if len(photos_json) > MAX_PHOTOS_JSON_LENGTH:
            raise HTTPException(413, "Les photos sont trop volumineuses. Réduisez leur nombre ou leur taille.")
        photo_count = len(clean)

    sell = SellRequest(
        brand=data.brand.strip(),
        model=data.model.strip(),
        year=data.year,
        mileage=data.mileage,
        name=data.name.strip(),
        phone=data.phone.strip(),
        email=str(data.email).lower(),
        notes=data.notes.strip(),
        photos=photos_json,
        status="new",
    )
    db.add(sell)
    await db.commit()

    await send_sell_request_email(
        sell.name, sell.email, sell.phone,
        f"{sell.brand} {sell.model} ({sell.year})", sell.mileage, sell.notes,
        photo_count=photo_count,
    )

    return {"ok": True, "message": "Merci ! Votre demande d'estimation a bien été envoyée. Nous vous recontactons sous 24h."}


# ── Admin : modération des avis ──────────────────────────

class AdminReviewOut(ReviewOut):
    email: str
    approved: bool

    class Config:
        from_attributes = True


class ReviewModeration(BaseModel):
    approved: bool


@router.get("/admin/reviews", response_model=List[AdminReviewOut])
async def admin_list_reviews(
    admin: object = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    approved: Optional[bool] = None,
):
    query = select(Review).order_by(desc(Review.created_at)).limit(200)
    if approved is not None:
        query = query.where(Review.approved == approved)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.patch("/admin/reviews/{review_id}")
async def admin_moderate_review(
    review_id: int,
    data: ReviewModeration,
    admin: object = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalars().first()
    if not review:
        raise HTTPException(404, "Avis introuvable")
    review.approved = data.approved
    await db.commit()
    return {"ok": True, "review_id": review.id, "approved": review.approved}


@router.delete("/admin/reviews/{review_id}")
async def admin_delete_review(
    review_id: int,
    admin: object = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Review).where(Review.id == review_id))
    review = result.scalars().first()
    if not review:
        raise HTTPException(404, "Avis introuvable")
    await db.delete(review)
    await db.commit()
    return {"ok": True, "message": f"Avis de {review.name} supprimé"}


# ── Admin : demandes de vente ────────────────────────────

class AdminSellRequestOut(BaseModel):
    id: int
    brand: str
    model: str
    year: int
    mileage: int
    name: str
    phone: str
    email: str
    notes: str
    photos: str  # JSON array de data-URLs
    photo_count: int = 0
    status: str
    created_at: object

    class Config:
        from_attributes = True


class SellRequestStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(new|contacted|closed)$")


@router.get("/admin/sell-requests", response_model=List[AdminSellRequestOut])
async def admin_list_sell_requests(
    admin: object = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = None,
):
    import json

    query = select(SellRequest).order_by(desc(SellRequest.created_at)).limit(200)
    if status:
        query = query.where(SellRequest.status == status)
    result = await db.execute(query)
    items = result.scalars().all()
    out = []
    for s in items:
        try:
            count = len(json.loads(s.photos or "[]"))
        except Exception:
            count = 0
        out.append(AdminSellRequestOut(
            id=s.id, brand=s.brand, model=s.model, year=s.year, mileage=s.mileage,
            name=s.name, phone=s.phone, email=s.email, notes=s.notes,
            photos=s.photos or "[]", photo_count=count, status=s.status,
            created_at=s.created_at,
        ))
    return out


@router.patch("/admin/sell-requests/{sell_id}/status")
async def admin_update_sell_request_status(
    sell_id: int,
    data: SellRequestStatusUpdate,
    admin: object = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SellRequest).where(SellRequest.id == sell_id))
    sell = result.scalars().first()
    if not sell:
        raise HTTPException(404, "Demande introuvable")
    sell.status = data.status
    await db.commit()
    return {"ok": True, "id": sell.id, "status": sell.status}


@router.delete("/admin/sell-requests/{sell_id}")
async def admin_delete_sell_request(
    sell_id: int,
    admin: object = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SellRequest).where(SellRequest.id == sell_id))
    sell = result.scalars().first()
    if not sell:
        raise HTTPException(404, "Demande introuvable")
    await db.delete(sell)
    await db.commit()
    return {"ok": True, "message": f"Demande de {sell.name} supprimée"}
