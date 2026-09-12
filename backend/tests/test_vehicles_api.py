"""Tests de l'API véhicules (catalogue public + création admin)."""


async def test_health_check(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_secured_endpoints_require_auth(client):
    resp = await client.get("/api/admin/vehicles")
    assert resp.status_code in (401, 403), resp.status_code


async def test_create_vehicle_requires_admin(client, db_session):
    resp = await client.post("/api/admin/vehicles", json={})
    assert resp.status_code in (401, 403), resp.status_code


async def test_public_catalog_filters(client, db_session):
    from app.models.commerce import Vehicle

    db_session.add(
        Vehicle(
            category="voiture",
            brand="Peugeot",
            model="308",
            year=2022,
            price=18000,
            monthly=250,
            is_active=True,
        )
    )
    await db_session.commit()

    resp = await client.get("/api/vehicles")
    assert resp.status_code == 200
    body = resp.json()
    items = body if isinstance(body, list) else body.get("vehicles", [])
    assert any(v.get("brand") == "Peugeot" for v in items)
