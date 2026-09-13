"""Veille de la base : health DB réel + backup admin téléchargeable."""

import json


async def test_health_reports_db_status(client):
    """Le health doit vérifier la base (SELECT 1) et exposer son état."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "ok"


async def test_backup_requires_auth(client):
    resp = await client.get("/api/admin/backup")
    assert resp.status_code in (401, 403), resp.status_code


async def test_backup_requires_admin(client, db_session, make_user):
    token = await _login_token(client, db_session, make_user, is_admin=False)
    resp = await client.get("/api/admin/backup", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403, resp.text


async def test_backup_exports_all_tables(client, db_session, make_user):
    """L'admin reçoit un JSON téléchargeable contenant les tables du schéma."""
    token = await _login_token(client, db_session, make_user, is_admin=True)
    resp = await client.get("/api/admin/backup", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert resp.headers.get("content-type", "").startswith("application/json")

    data = json.loads(resp.content.decode("utf-8"))
    from app.database import Base

    for table in Base.metadata.sorted_tables:
        assert table.name in data, f"table manquante dans le backup : {table.name}"
    assert isinstance(data["users"], list)


async def _login_token(client, db_session, make_user, is_admin: bool) -> str:
    user = await make_user(
        db_session, email="backup-user@autoprestige.fr", is_admin=is_admin
    )
    resp = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "ClientPassword123!"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]
