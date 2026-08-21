from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.commerce import (
    CartItem, Order, Installment, Delivery, DeliveryEvent,
    PaymentType, OrderStatus, DeliveryStatus
)
from app.schemas import CheckoutIn, OrderOut, PayInstallmentIn, DeliveryDetailsIn
from app.deps import get_current_user

router = APIRouter(prefix="/orders", tags=["Orders"])


def _order_query():
    return select(Order).options(
        selectinload(Order.installments),
        selectinload(Order.delivery).selectinload(Delivery.events),
    )


@router.get("", response_model=list[OrderOut])
async def list_orders(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        _order_query().where(Order.user_id == user.id).order_by(Order.created_at.desc())
    )
    return [OrderOut.model_validate(o) for o in result.scalars().all()]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        _order_query().where(Order.id == order_id, Order.user_id == user.id)
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(404, "Commande introuvable.")
    return OrderOut.model_validate(order)


@router.post("/checkout", response_model=OrderOut)
async def checkout(
    data: CheckoutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Get cart item
    result = await db.execute(
        select(CartItem).where(CartItem.id == data.cart_item_id, CartItem.user_id == user.id)
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(404, "Article panier introuvable.")

    total = item.price
    monthly_amount = 0.0
    months_total = 0
    amount_paid = 0.0
    status = OrderStatus.PENDING.value

    if data.payment_type == PaymentType.FULL.value:
        amount_paid = total
        status = OrderStatus.PAID.value
    else:
        months = data.months or 48
        months_total = months
        monthly_amount = round(total / months, 2)
        status = OrderStatus.ACTIVE.value

    order = Order(
        user_id=user.id,
        vehicle_id=item.vehicle_id,
        brand=item.brand,
        model=item.model,
        year=item.year,
        image=item.image,
        total_price=total,
        payment_type=data.payment_type,
        monthly_amount=monthly_amount,
        months_total=months_total,
        amount_paid=amount_paid,
        status=status,
        paid_at=datetime.now(timezone.utc) if data.payment_type == "full" else None,
    )
    db.add(order)
    await db.flush()

    # Create installment schedule for monthly
    if data.payment_type == PaymentType.MONTHLY.value:
        start = datetime.now(timezone.utc)
        for i in range(1, months_total + 1):
            due = start + timedelta(days=30 * i)
            inst = Installment(
                order_id=order.id,
                number=i,
                amount=monthly_amount,
                due_date=due,
                paid=False,
            )
            db.add(inst)

    # If fully paid → create delivery
    if status == OrderStatus.PAID.value:
        order.status = OrderStatus.DELIVERING.value
        delivery = Delivery(
            order_id=order.id,
            status=DeliveryStatus.PREPARING.value,
            tracking_number=f"AP-{order.id:06d}-{item.vehicle_id}",
            carrier="AutoPrestige Logistics",
            estimated_delivery=datetime.now(timezone.utc) + timedelta(days=14),
            current_location="Centre de préparation — Paris",
            notes="Véhicule en cours de préparation.",
        )
        db.add(delivery)
        await db.flush()
        db.add(DeliveryEvent(
            delivery_id=delivery.id,
            status=DeliveryStatus.PREPARING.value,
            location="Paris, France",
            message="Commande confirmée. Préparation du véhicule en cours.",
        ))

    # Remove from cart
    await db.delete(item)
    await db.commit()

    # Reload with relations
    result = await db.execute(_order_query().where(Order.id == order.id))
    order = result.scalars().first()
    return OrderOut.model_validate(order)


@router.patch("/{order_id}/delivery-details", response_model=OrderOut)
async def save_delivery_details(
    order_id: int,
    data: DeliveryDetailsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        _order_query().where(Order.id == order_id, Order.user_id == user.id)
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(404, "Commande introuvable.")
    if (order.amount_paid or 0) + 0.01 < order.total_price:
        raise HTTPException(400, "La commande doit être totalement soldée avant la livraison.")

    delivery = order.delivery
    if not delivery:
        delivery = Delivery(order_id=order.id)
        db.add(delivery)
        await db.flush()
    for field, value in data.model_dump().items():
        setattr(delivery, field, value.strip())
    delivery.updated_at = datetime.now(timezone.utc)
    await db.commit()

    result = await db.execute(_order_query().where(Order.id == order.id))
    return OrderOut.model_validate(result.scalars().first())


@router.post("/{order_id}/pay-installment", response_model=OrderOut)
async def pay_installment(
    order_id: int,
    data: PayInstallmentIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Le client déclare avoir effectué le virement pour cette échéance.
    Statut → claimed. L'admin doit valider après vérification bancaire.
    """
    from app.models.commerce import Notification, InstallmentPaymentStatus

    result = await db.execute(
        _order_query().where(Order.id == order_id, Order.user_id == user.id)
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(404, "Commande introuvable.")
    if order.payment_type != "monthly":
        raise HTTPException(400, "Cette commande n'est pas en paiement mensuel.")

    inst = next((i for i in order.installments if i.id == data.installment_id), None)
    if not inst:
        raise HTTPException(404, "Échéance introuvable.")
    if inst.paid or inst.payment_status == InstallmentPaymentStatus.PAID.value:
        raise HTTPException(400, "Cette échéance est déjà payée.")
    if inst.payment_status == InstallmentPaymentStatus.CLAIMED.value:
        raise HTTPException(400, "Paiement déjà déclaré — en attente de validation admin.")

    # Must claim in order (skip already paid)
    unpaid = sorted(
        [i for i in order.installments if not i.paid and i.payment_status != InstallmentPaymentStatus.PAID.value],
        key=lambda x: x.number,
    )
    if unpaid and unpaid[0].id != inst.id:
        raise HTTPException(400, f"Veuillez d'abord régler l'échéance n°{unpaid[0].number}.")

    inst.payment_status = InstallmentPaymentStatus.CLAIMED.value
    inst.claimed_at = datetime.now(timezone.utc)

    # Notification pour l'admin
    notif = Notification(
        type="payment_claim",
        title=f"Paiement déclaré — échéance n°{inst.number}",
        message=(
            f"{user.first_name} {user.last_name} ({user.email}) déclare avoir payé "
            f"{inst.amount:.2f} € pour la commande #{order.id} "
            f"({order.brand} {order.model}). Vérifiez le virement puis validez."
        ),
        user_id=user.id,
        order_id=order.id,
        installment_id=inst.id,
    )
    db.add(notif)
    await db.commit()

    result = await db.execute(_order_query().where(Order.id == order.id))
    order = result.scalars().first()
    return OrderOut.model_validate(order)


@router.get("/{order_id}/delivery", response_model=OrderOut)
async def get_delivery(order_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        _order_query().where(Order.id == order_id, Order.user_id == user.id)
    )
    order = result.scalars().first()
    if not order:
        raise HTTPException(404, "Commande introuvable.")
    if not order.delivery:
        raise HTTPException(400, "Livraison pas encore disponible. Soldez d'abord la commande.")
    return OrderOut.model_validate(order)
