"""Tests du parcours panier → commande (checkout)."""

from sqlalchemy import select

from app.models.commerce import CartItem


async def test_cart_and_checkout_flow(client, db_session, auth_headers):
    from app.models.commerce import Vehicle

    vehicle = Vehicle(
        category="voiture",
        brand="Renault",
        model="Clio",
        year=2021,
        price=10000,
        monthly=140,
        is_active=True,
    )
    db_session.add(vehicle)
    await db_session.commit()
    await db_session.refresh(vehicle)

    token, user = auth_headers

    # Le body ne doit PAS influencer le prix : tout est rechargé du catalogue.
    resp = await client.post(
        "/api/cart/add",
        headers={"Authorization": f"Bearer {token}"},
        json={"vehicle_id": vehicle.id, "price": 1, "brand": "Fake", "model": "Fake"},
    )
    assert resp.status_code == 200, resp.text
    item = resp.json()
    assert item["price"] == 10000, "Le prix doit venir du serveur, pas du client"
    assert item["brand"] == "Renault", "La marque doit venir du serveur"

    cart = await client.get("/api/cart", headers={"Authorization": f"Bearer {token}"})
    assert cart.status_code == 200
    assert cart.json()["count"] == 1
    assert cart.json()["total"] == 10000

    order = await client.post(
        "/api/orders/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"cart_item_id": item["id"], "payment_type": "monthly", "months": 48},
    )
    assert order.status_code == 200, order.text
    body = order.json()
    assert body["status"] == "active"
    assert body["payment_type"] == "monthly"
    assert len(body["installments"]) > 0


async def test_checkout_rejects_foreign_cart_item(client, db_session, make_user, auth_headers):
    from app.models.commerce import Vehicle

    vehicle = Vehicle(
        category="voiture",
        brand="Volkswagen",
        model="Golf",
        year=2019,
        price=15000,
        monthly=210,
        is_active=True,
    )
    db_session.add(vehicle)
    await db_session.commit()
    await db_session.refresh(vehicle)

    token, user = auth_headers

    # Un autre utilisateur ajoute le véhicule à SON panier.
    other = await make_user(db_session, email="other@example.com")

    db_session.add(
        CartItem(
            user_id=other.id,
            vehicle_id=vehicle.id,
            brand=vehicle.brand,
            model=vehicle.model,
            year=vehicle.year,
            price=vehicle.price,
            monthly=vehicle.monthly,
            image="",
        )
    )
    await db_session.commit()
    foreign_item_id = (
        await db_session.execute(
            select(CartItem.id).where(CartItem.user_id == other.id)
        )
    ).scalar()

    resp = await client.post(
        "/api/orders/checkout",
        headers={"Authorization": f"Bearer {token}"},
        json={"cart_item_id": foreign_item_id, "payment_type": "full"},
    )
    assert resp.status_code == 404, resp.text
