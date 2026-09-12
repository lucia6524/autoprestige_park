"""API /vehicles — descriptions localisées via ?lang= (phase 3 SEO).

Contrats : langue supportée → description_<lang> si non vide ; repli FR
garanti sinon ; langue inconnue → 422 ; sans ?lang= → comportement historique.
"""

from app.models.commerce import Vehicle


async def _seed(db, **overrides) -> Vehicle:
    data = dict(
        category="voiture",
        brand="BMW",
        model="Série 1",
        year=2020,
        fuel="Essence",
        transmission="Automatique",
        mileage=10000,
        price=20000.0,
        monthly=250.0,
        type="occasion",
        body_category="Berline",
        power=150,
        is_active=True,
        image="",
        images="[]",
        description="Description française de test.",
        description_en="English test description.",
        description_de="",  # volontairement non traduit → repli FR
    )
    data.update(overrides)
    v = Vehicle(**data)
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


async def test_lang_en_returns_translated_description(client, db_session):
    v = await _seed(db_session)
    resp = await client.get(f"/api/vehicles/{v.id}", params={"lang": "en"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "English test description."


async def test_lang_missing_translation_falls_back_to_french(client, db_session):
    v = await _seed(db_session)
    resp = await client.get(f"/api/vehicles/{v.id}", params={"lang": "de"})
    assert resp.status_code == 200, resp.text
    # description_de vide → repli FR garanti (jamais de description vide)
    assert resp.json()["description"] == "Description française de test."


async def test_no_lang_keeps_french_description(client, db_session):
    v = await _seed(db_session)
    resp = await client.get(f"/api/vehicles/{v.id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "Description française de test."


async def test_invalid_lang_is_rejected(client, db_session):
    v = await _seed(db_session)
    resp = await client.get(f"/api/vehicles/{v.id}", params={"lang": "xx"})
    assert resp.status_code == 422, resp.text


async def test_lang_applies_to_catalog_list(client, db_session):
    await _seed(db_session)
    resp = await client.get("/api/vehicles", params={"lang": "en"})
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert items and all(i["description"] for i in items)
    assert any(i["description"] == "English test description." for i in items)
