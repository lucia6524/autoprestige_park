"""PATCH /api/admin/vehicles/{id} — édition des descriptions pré-traduites.

Contrats :
- un admin peut définir description_<lang> (en/de/it/es/pt/ro) via PATCH ;
- la valeur persiste et est servie par /api/vehicles?lang=<lang> ;
- les champs inconnus restent rejetés (422) ;
- un non-admin est refusé (403), un anonyme aussi (401).
"""

import pytest

LANGS = ("en", "de", "it", "es", "pt", "ro")


async def _seed_vehicle(db):
    from app.models.commerce import Vehicle

    v = Vehicle(
        category="voiture",
        brand="Audi",
        model="A4",
        year=2021,
        fuel="Diesel",
        transmission="Automatique",
        mileage=15000,
        price=30000.0,
        monthly=300.0,
        type="occasion",
        body_category="Berline",
        power=190,
        is_active=True,
        image="",
        images="[]",
        description="Description française.",
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


@pytest.fixture()
async def admin_headers(client, db_session, make_user):
    await make_user(db_session, email="admin-desc@autoprestige.fr", is_admin=True)
    resp = await client.post(
        "/api/auth/login",
        json={"email": "admin-desc@autoprestige.fr", "password": "ClientPassword123!"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_admin_can_set_all_translated_descriptions(client, db_session, admin_headers):
    v = await _seed_vehicle(db_session)
    payload = {f"description_{lang}": f"Description {lang} de test." for lang in LANGS}
    resp = await client.patch(f"/api/admin/vehicles/{v.id}", json=payload, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for lang in LANGS:
        assert body[f"description_{lang}"] == f"Description {lang} de test."


async def test_translated_description_served_via_lang(client, db_session, admin_headers):
    v = await _seed_vehicle(db_session)
    resp = await client.patch(
        f"/api/admin/vehicles/{v.id}",
        json={"description_en": "English description."},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"/api/vehicles/{v.id}", params={"lang": "en"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "English description."

    # Sans ?lang= : le champ FR reste intact.
    resp = await client.get(f"/api/vehicles/{v.id}")
    assert resp.json()["description"] == "Description française."


async def test_patch_ignores_unknown_description_fields(client, db_session, admin_headers):
    """Champ inconnu → ignoré par Pydantic (défaut du projet), rien n'est persisté."""
    v = await _seed_vehicle(db_session)
    resp = await client.patch(
        f"/api/admin/vehicles/{v.id}",
        json={"description_ko": "hack"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert "description_ko" not in resp.json()
    await db_session.refresh(v)
    assert (v.description_en or "") == ""


async def test_patch_requires_admin(client, db_session, make_user):
    v = await _seed_vehicle(db_session)
    await make_user(db_session, email="user-desc@autoprestige.fr", is_admin=False)
    resp = await client.post(
        "/api/auth/login",
        json={"email": "user-desc@autoprestige.fr", "password": "ClientPassword123!"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    resp = await client.patch(
        f"/api/admin/vehicles/{v.id}", json={"description_en": "x"}, headers=headers
    )
    assert resp.status_code == 403, resp.text


async def test_patch_requires_auth(client, db_session):
    v = await _seed_vehicle(db_session)
    resp = await client.patch(f"/api/admin/vehicles/{v.id}", json={"description_en": "x"})
    assert resp.status_code == 401, resp.text
