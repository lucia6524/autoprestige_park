"""
Admin API — réservé aux utilisateurs is_admin=True
"""
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db
from app.deps import get_current_admin
from app.models.user import User
from app.models.commerce import Order, CartItem, Installment, Delivery, DeliveryEvent
from app.services.auth import hash_password

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Schemas ──────────────────────────────────────────────

class AdminStats(BaseModel):
    users_total: int
    users_verified: int
    orders_total: int
    orders_pending: int
    orders_active: int
    orders_paid: int
    revenue_total: float
    revenue_pending: float


class AdminUserOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    phone: str
    monthly_salary: float
    is_verified: bool
    is_active: bool
    is_admin: bool
    created_at: datetime
    orders_count: int = 0

    class Config:
        from_attributes = True


class AdminUserUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    is_verified: Optional[bool] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None


class AdminOrderOut(BaseModel):
    id: int
    user_id: int
    user_email: str = ""
    user_name: str = ""
    vehicle_id: int
    brand: str
    model: str
    year: int
    image: str
    total_price: float
    payment_type: str
    monthly_amount: float
    months_total: int
    amount_paid: float
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    delivery_status: Optional[str] = None
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    current_location: Optional[str] = None
    delivery_notes: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    recipient_first_name: Optional[str] = None
    recipient_last_name: Optional[str] = None
    recipient_phone: Optional[str] = None
    delivery_address: Optional[str] = None

    class Config:
        from_attributes = True


class OrderStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(pending|active|paid|delivering|delivered|cancelled)$")


class DeliveryUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(preparing|shipped|in_transit|out_for_delivery|delivered)$")
    tracking_number: Optional[str] = None
    carrier: Optional[str] = None
    current_location: Optional[str] = None
    notes: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    event_message: Optional[str] = None


# ── Dashboard stats ──────────────────────────────────────

@router.get("/stats", response_model=AdminStats)
async def admin_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    users_total = (await db.execute(select(func.count(User.id)))).scalar() or 0
    users_verified = (await db.execute(
        select(func.count(User.id)).where(User.is_verified == True)
    )).scalar() or 0

    orders_total = (await db.execute(select(func.count(Order.id)))).scalar() or 0
    orders_pending = (await db.execute(
        select(func.count(Order.id)).where(Order.status == "pending")
    )).scalar() or 0
    orders_active = (await db.execute(
        select(func.count(Order.id)).where(Order.status == "active")
    )).scalar() or 0
    orders_paid = (await db.execute(
        select(func.count(Order.id)).where(Order.status.in_(["paid", "delivered"]))
    )).scalar() or 0

    revenue_total = (await db.execute(
        select(func.coalesce(func.sum(Order.amount_paid), 0.0))
    )).scalar() or 0.0
    revenue_pending = (await db.execute(
        select(func.coalesce(func.sum(Order.total_price - Order.amount_paid), 0.0)).where(
            Order.status.in_(["pending", "active", "delivering"])
        )
    )).scalar() or 0.0

    return AdminStats(
        users_total=users_total,
        users_verified=users_verified,
        orders_total=orders_total,
        orders_pending=orders_pending,
        orders_active=orders_active,
        orders_paid=orders_paid,
        revenue_total=float(revenue_total),
        revenue_pending=float(revenue_pending),
    )


# ── Users ────────────────────────────────────────────────

@router.get("/users", response_model=List[AdminUserOut])
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 50,
):
    query = select(User).order_by(desc(User.created_at)).offset(skip).limit(limit)
    if q:
        like = f"%{q.lower()}%"
        query = select(User).where(
            (func.lower(User.email).like(like))
            | (func.lower(User.first_name).like(like))
            | (func.lower(User.last_name).like(like))
        ).order_by(desc(User.created_at)).offset(skip).limit(limit)

    result = await db.execute(query)
    users = result.scalars().all()

    out = []
    for u in users:
        count = (await db.execute(
            select(func.count(Order.id)).where(Order.user_id == u.id)
        )).scalar() or 0
        out.append(AdminUserOut(
            id=u.id,
            first_name=u.first_name,
            last_name=u.last_name,
            email=u.email,
            phone=u.phone or "",
            monthly_salary=u.monthly_salary or 0,
            is_verified=u.is_verified,
            is_active=u.is_active,
            is_admin=bool(getattr(u, "is_admin", False)),
            created_at=u.created_at,
            orders_count=count,
        ))
    return out


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")

    # Empêcher de se retirer les droits admin soi-même
    if user.id == admin.id and data.is_admin is False:
        raise HTTPException(400, "Vous ne pouvez pas retirer vos propres droits admin")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    count = (await db.execute(
        select(func.count(Order.id)).where(Order.user_id == user.id)
    )).scalar() or 0

    return AdminUserOut(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        phone=user.phone or "",
        monthly_salary=user.monthly_salary or 0,
        is_verified=user.is_verified,
        is_active=user.is_active,
        is_admin=bool(user.is_admin),
        created_at=user.created_at,
        orders_count=count,
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(400, "Vous ne pouvez pas supprimer votre propre compte")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    await db.delete(user)
    await db.commit()
    return {"ok": True, "message": f"Utilisateur {user.email} supprimé"}


# ── Orders ───────────────────────────────────────────────

@router.get("/orders", response_model=List[AdminOrderOut])
async def list_orders(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    query = select(Order).options(
        selectinload(Order.user), selectinload(Order.delivery)
    ).order_by(desc(Order.created_at)).offset(skip).limit(limit)
    if status:
        query = select(Order).options(
            selectinload(Order.user), selectinload(Order.delivery)
        ).where(
            Order.status == status
        ).order_by(desc(Order.created_at)).offset(skip).limit(limit)

    result = await db.execute(query)
    orders = result.scalars().all()

    out = []
    for o in orders:
        u = o.user
        out.append(AdminOrderOut(
            id=o.id,
            user_id=o.user_id,
            user_email=u.email if u else "",
            user_name=f"{u.first_name} {u.last_name}" if u else "",
            vehicle_id=o.vehicle_id,
            brand=o.brand,
            model=o.model,
            year=o.year,
            image=o.image or "",
            total_price=o.total_price,
            payment_type=o.payment_type,
            monthly_amount=o.monthly_amount or 0,
            months_total=o.months_total or 0,
            amount_paid=o.amount_paid or 0,
            status=o.status,
            created_at=o.created_at,
            paid_at=o.paid_at,
            delivery_status=o.delivery.status if o.delivery else None,
            tracking_number=o.delivery.tracking_number if o.delivery else None,
            carrier=o.delivery.carrier if o.delivery else None,
            current_location=o.delivery.current_location if o.delivery else None,
            delivery_notes=o.delivery.notes if o.delivery else None,
            estimated_delivery=o.delivery.estimated_delivery if o.delivery else None,
            recipient_first_name=o.delivery.recipient_first_name if o.delivery else None,
            recipient_last_name=o.delivery.recipient_last_name if o.delivery else None,
            recipient_phone=o.delivery.recipient_phone if o.delivery else None,
            delivery_address=o.delivery.delivery_address if o.delivery else None,
        ))
    return out


@router.patch("/orders/{order_id}/status")
async def update_order_status(
    order_id: int,
    data: OrderStatusUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalars().first()
    if not order:
        raise HTTPException(404, "Commande introuvable")

    order.status = data.status
    if data.status == "paid" and not order.paid_at:
        order.paid_at = datetime.now(timezone.utc)
        order.amount_paid = order.total_price

    await db.commit()
    return {"ok": True, "order_id": order.id, "status": order.status}


@router.patch("/orders/{order_id}/delivery")
async def update_delivery(
    order_id: int,
    data: DeliveryUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Order).options(selectinload(Order.delivery)).where(Order.id == order_id)
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(404, "Commande introuvable")

    delivery = order.delivery
    if not delivery:
        delivery = Delivery(order_id=order.id)
        db.add(delivery)
        await db.flush()

    if data.status is not None:
        delivery.status = data.status
        # Sync order status when delivering
        if data.status in ("shipped", "in_transit"):
            order.status = "delivering"
        elif data.status == "delivered":
            order.status = "delivered"
    if data.tracking_number is not None:
        delivery.tracking_number = data.tracking_number
    if data.carrier is not None:
        delivery.carrier = data.carrier
    if data.current_location is not None:
        delivery.current_location = data.current_location
    if data.notes is not None:
        delivery.notes = data.notes
    if data.estimated_delivery is not None:
        delivery.estimated_delivery = data.estimated_delivery

    delivery.updated_at = datetime.now(timezone.utc)

    if data.event_message or data.status:
        event = DeliveryEvent(
            delivery_id=delivery.id,
            status=data.status or delivery.status,
            location=data.current_location or delivery.current_location or "",
            message=data.event_message or f"Statut mis à jour : {data.status or delivery.status}",
        )
        db.add(event)

    await db.commit()
    return {
        "ok": True,
        "order_id": order.id,
        "delivery_status": delivery.status,
        "tracking_number": delivery.tracking_number,
    }


# ── Vehicles CRUD ────────────────────────────────────────

class VehicleIn(BaseModel):
    category: str = Field(..., pattern="^(voiture|camping-car|machine-agricole)$")
    brand: str
    model: str
    year: int = 2024
    fuel: str = ""
    transmission: str = ""
    mileage: int = 0
    price: float
    monthly: float = 0
    type: str = "occasion"  # neuf | occasion
    body_category: str = ""
    power: int = 0
    featured: bool = False
    promo: bool = False
    is_active: bool = True
    image: str = ""
    images: str = ""  # JSON string array
    description: str = ""


class VehicleOut(BaseModel):
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
    is_active: bool
    image: str
    images: str
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


class VehicleUpdate(BaseModel):
    category: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    fuel: Optional[str] = None
    transmission: Optional[str] = None
    mileage: Optional[int] = None
    price: Optional[float] = None
    monthly: Optional[float] = None
    type: Optional[str] = None
    body_category: Optional[str] = None
    power: Optional[int] = None
    featured: Optional[bool] = None
    promo: Optional[bool] = None
    is_active: Optional[bool] = None
    image: Optional[str] = None
    images: Optional[str] = None
    description: Optional[str] = None


from app.models.commerce import Vehicle, Notification, Installment, InstallmentPaymentStatus


@router.get("/vehicles", response_model=List[VehicleOut])
async def list_vehicles(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    category: Optional[str] = None,
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
):
    query = select(Vehicle).order_by(desc(Vehicle.created_at))
    if category:
        query = query.where(Vehicle.category == category)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(
            (func.lower(Vehicle.brand).like(like))
            | (func.lower(Vehicle.model).like(like))
        )
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/vehicles", response_model=VehicleOut)
async def create_vehicle(
    data: VehicleIn,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    v = Vehicle(**data.model_dump())
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
async def update_vehicle(
    vehicle_id: int,
    data: VehicleUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    v = result.scalars().first()
    if not v:
        raise HTTPException(404, "Véhicule introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(v, field, value)
    await db.commit()
    await db.refresh(v)
    return v


@router.delete("/vehicles/{vehicle_id}")
async def delete_vehicle(
    vehicle_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
    v = result.scalars().first()
    if not v:
        raise HTTPException(404, "Véhicule introuvable")
    await db.delete(v)
    await db.commit()
    return {"ok": True, "message": f"{v.brand} {v.model} supprimé"}


# ── Public catalogue (no auth) — pour le frontend ────────
# Note: registered on admin router under /admin/vehicles/public is awkward.
# We'll add a separate public route in main or vehicles router later.


# ── Payment claims (échéances déclarées par les clients) ─

class PaymentClaimOut(BaseModel):
    installment_id: int
    order_id: int
    number: int
    amount: float
    due_date: datetime
    payment_status: str
    claimed_at: Optional[datetime]
    admin_note: str
    brand: str
    model: str
    user_id: int
    user_name: str
    user_email: str


class PaymentClaimAction(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    admin_note: str = ""


@router.get("/payment-claims", response_model=List[PaymentClaimOut])
async def list_payment_claims(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = "claimed",
):
    """Liste des échéances en attente de validation (ou filtrées par status)."""
    query = (
        select(Installment)
        .options(selectinload(Installment.order).selectinload(Order.user))
        .order_by(desc(Installment.claimed_at))
    )
    if status:
        query = query.where(Installment.payment_status == status)
    result = await db.execute(query)
    items = result.scalars().all()
    out = []
    for inst in items:
        o = inst.order
        u = o.user if o else None
        out.append(PaymentClaimOut(
            installment_id=inst.id,
            order_id=o.id if o else 0,
            number=inst.number,
            amount=inst.amount,
            due_date=inst.due_date,
            payment_status=inst.payment_status,
            claimed_at=inst.claimed_at,
            admin_note=inst.admin_note or "",
            brand=o.brand if o else "",
            model=o.model if o else "",
            user_id=u.id if u else 0,
            user_name=f"{u.first_name} {u.last_name}" if u else "",
            user_email=u.email if u else "",
        ))
    return out


@router.post("/payment-claims/{installment_id}")
async def resolve_payment_claim(
    installment_id: int,
    data: PaymentClaimAction,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Admin valide ou refuse un paiement déclaré.
    approve → échéance payée + maj commande
    reject  → client peut re-déclarer
    """
    from app.models.commerce import Delivery, DeliveryEvent, DeliveryStatus, OrderStatus
    from datetime import timedelta

    result = await db.execute(
        select(Installment)
        .options(selectinload(Installment.order).selectinload(Order.installments))
        .where(Installment.id == installment_id)
    )
    inst = result.scalars().first()
    if not inst:
        raise HTTPException(404, "Échéance introuvable")
    if inst.payment_status != InstallmentPaymentStatus.CLAIMED.value:
        raise HTTPException(400, f"Cette échéance n'est pas en attente (statut: {inst.payment_status})")

    order = inst.order
    inst.admin_note = data.admin_note or ""

    if data.action == "reject":
        inst.payment_status = InstallmentPaymentStatus.REJECTED.value
        inst.claimed_at = None
        # Mark related notifications as read
        notifs = await db.execute(
            select(Notification).where(
                Notification.installment_id == inst.id,
                Notification.is_read == False,
            )
        )
        for n in notifs.scalars().all():
            n.is_read = True
        await db.commit()
        return {"ok": True, "action": "rejected", "installment_id": inst.id}

    # APPROVE
    inst.payment_status = InstallmentPaymentStatus.PAID.value
    inst.paid = True
    inst.paid_at = datetime.now(timezone.utc)
    order.amount_paid = round((order.amount_paid or 0) + inst.amount, 2)

    if all(i.paid for i in order.installments):
        order.status = OrderStatus.PAID.value
        order.paid_at = datetime.now(timezone.utc)
        if not order.delivery:
            delivery = Delivery(
                order_id=order.id,
                status=DeliveryStatus.PREPARING.value,
                tracking_number=f"AP-{order.id:06d}-{order.vehicle_id}",
                carrier="AutoPrestige Logistics",
                estimated_delivery=datetime.now(timezone.utc) + timedelta(days=14),
                current_location="Centre de préparation — Paris",
            )
            db.add(delivery)
            await db.flush()
            db.add(DeliveryEvent(
                delivery_id=delivery.id,
                status=DeliveryStatus.PREPARING.value,
                location="Paris, France",
                message="Solde réglé et validé. Préparation du véhicule pour expédition.",
            ))
    # Mark notifications read
    notifs = await db.execute(
        select(Notification).where(
            Notification.installment_id == inst.id,
            Notification.is_read == False,
        )
    )
    for n in notifs.scalars().all():
        n.is_read = True

    await db.commit()
    return {
        "ok": True,
        "action": "approved",
        "installment_id": inst.id,
        "order_id": order.id,
        "order_status": order.status,
        "amount_paid": order.amount_paid,
    }


# ── Notifications ────────────────────────────────────────

class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    message: str
    user_id: Optional[int]
    order_id: Optional[int]
    installment_id: Optional[int]
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/notifications", response_model=List[NotificationOut])
async def list_notifications(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    unread_only: bool = False,
    limit: int = 50,
):
    query = select(Notification).order_by(desc(Notification.created_at)).limit(limit)
    if unread_only:
        query = query.where(Notification.is_read == False)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("/notifications/{notif_id}/read")
async def mark_notification_read(
    notif_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Notification).where(Notification.id == notif_id))
    n = result.scalars().first()
    if not n:
        raise HTTPException(404, "Notification introuvable")
    n.is_read = True
    await db.commit()
    return {"ok": True}
