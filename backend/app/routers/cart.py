from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.models.user import User
from app.models.commerce import CartItem
from app.schemas import CartItemIn, CartItemOut, CartOut
from app.deps import get_current_user

router = APIRouter(prefix="/cart", tags=["Cart"])


@router.get("", response_model=CartOut)
async def get_cart(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CartItem).where(CartItem.user_id == user.id))
    items = result.scalars().all()
    total = sum(i.price for i in items)
    return CartOut(
        items=[CartItemOut.model_validate(i) for i in items],
        total=total,
        count=len(items),
    )


@router.post("/add", response_model=CartItemOut)
async def add_to_cart(
    data: CartItemIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Prevent duplicates
    result = await db.execute(
        select(CartItem).where(
            CartItem.user_id == user.id,
            CartItem.vehicle_id == data.vehicle_id,
        )
    )
    existing = result.scalars().first()
    if existing:
        raise HTTPException(400, "Ce véhicule est déjà dans votre panier.")

    item = CartItem(
        user_id=user.id,
        vehicle_id=data.vehicle_id,
        brand=data.brand,
        model=data.model,
        year=data.year,
        price=data.price,
        monthly=data.monthly,
        image=data.image,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return CartItemOut.model_validate(item)


@router.delete("/{item_id}")
async def remove_from_cart(
    item_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CartItem).where(CartItem.id == item_id, CartItem.user_id == user.id)
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(404, "Article introuvable dans le panier.")
    await db.delete(item)
    await db.commit()
    return {"ok": True, "message": "Véhicule retiré du panier."}


@router.delete("")
async def clear_cart(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(delete(CartItem).where(CartItem.user_id == user.id))
    await db.commit()
    return {"ok": True, "message": "Panier vidé."}
