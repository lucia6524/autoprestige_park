"""API /site-settings — formulaires « Informations du site » de l'admin.

Le front admin met à jour chaque champ via PUT /api/site-settings (un
formulaire autonome par champ). Le preflight CORS doit donc accepter PUT :
sinon le navigateur bloque la requête et l'admin voit un échec générique.
"""

import pytest


async def _login_token(client, db_session, make_user, is_admin: bool) -> str:
    user = await make_user(
        db_session, email="settings-user@autoprestige.fr", is_admin=is_admin
    )
    resp = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "ClientPassword123!"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture()
def _prod_origin():
    """Ajoute l'origine de production aux origines autorisées.

    Le middleware CORS capture l'objet liste au montage de l'app : on le
    mute en place (append/remove) plutôt que de remplacer l'attribut, sinon
    la modification n'est pas vue du middleware. (Les wildcards
    « http://localhost:* » du mode dev ne sont de toute façon pas
    interprétés par le middleware CORS de Starlette.)"""
    from app.config import settings

    origin = "https://autohaus-park.onrender.com"
    settings.CORS_ORIGINS.append(origin)
    yield
    settings.CORS_ORIGINS.remove(origin)


async def test_cors_preflight_allows_put_on_site_settings(client, _prod_origin):
    """Le preflight doit lister PUT dans Access-Control-Allow-Methods."""
    resp = await client.options(
        "/api/site-settings",
        headers={
            "Origin": "https://autohaus-park.onrender.com",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert resp.status_code == 200, resp.text
    allow = resp.headers.get("access-control-allow-methods", "")
    assert "PUT" in [m.strip() for m in allow.split(",")], allow


async def test_admin_can_update_site_settings(client, db_session, make_user):
    """PUT partiel par l'admin : champ modifié, autres champs conservés."""
    token = await _login_token(client, db_session, make_user, is_admin=True)
    resp = await client.put(
        "/api/site-settings",
        json={"contact_phone": "+33 6 12 34 56 78"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["contact_phone"] == "+33 6 12 34 56 78"
    # Mise à jour partielle : la valeur par défaut des autres champs reste.
    assert data["contact_email"]  # non vide => non écrasé par le PUT partiel


async def test_update_site_settings_requires_admin(client, db_session, make_user):
    """Un compte non admin doit recevoir 403."""
    token = await _login_token(client, db_session, make_user, is_admin=False)
    resp = await client.put(
        "/api/site-settings",
        json={"contact_phone": "+33 6 12 34 56 78"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text


async def test_update_site_settings_requires_auth(client):
    """Sans token : 401."""
    resp = await client.put(
        "/api/site-settings",
        json={"contact_phone": "+33 6 12 34 56 78"},
    )
    assert resp.status_code == 401, resp.text
