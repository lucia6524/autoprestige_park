"""Tests du flux d'authentification en 5 étapes (inscription OTP + connexion)."""

PASSWORD = "ClientPassword123!"


async def _register(client, email):
    """Inscription complète via l'API (étapes 1→5) et retour du token."""
    r1 = await client.post(
        "/api/auth/register/step1",
        json={"first_name": "Jean", "last_name": "Martin"},
    )
    assert r1.status_code == 200, r1.text
    session_key = r1.json()["session_key"]

    r2 = await client.post(
        f"/api/auth/register/step2?session_key={session_key}",
        json={"email": email, "phone": "+33123456789"},
    )
    assert r2.status_code == 200, r2.text

    r3 = await client.post(
        f"/api/auth/register/step3?session_key={session_key}",
        json={"monthly_salary": 3000},
    )
    assert r3.status_code == 200, r3.text
    body = r3.json()
    assert "dev_code" in body, "En dev, le code OTP doit être renvoyé"
    code = body["dev_code"]

    r4 = await client.post(
        "/api/auth/register/verify",
        json={"email": email, "code": code},
    )
    assert r4.status_code == 200, r4.text
    reg_token = r4.json()["registration_token"]

    r5 = await client.post(
        "/api/auth/register/set-password",
        json={"email": email, "password": PASSWORD, "registration_token": reg_token},
    )
    assert r5.status_code == 200, r5.text
    return r5.json()["access_token"]


async def test_full_registration_logs_in(client):
    token = await _register(client, "jean.martin@example.com")
    assert token

    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["email"] == "jean.martin@example.com"
    assert me["is_verified"] is True


async def test_login_wrong_password(client, db_session, make_user):
    await make_user(db_session, email="pwd@example.com", password=PASSWORD)
    resp = await client.post(
        "/api/auth/login",
        json={"email": "pwd@example.com", "password": "WrongPassword1!"},
    )
    assert resp.status_code == 401


async def test_login_ok(client, db_session, make_user):
    await make_user(db_session, email="login@example.com", password=PASSWORD)
    resp = await client.post(
        "/api/auth/login",
        json={"email": "login@example.com", "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    assert "access_token" in resp.json()


async def test_register_rejects_weak_password(client):
    token = await _register(client, "weak@example.com")
    # Assez long pour passer la validation pydantic, mais sans majuscule :
    # doit être refusé par la politique de robustesse serveur (400).
    resp = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": PASSWORD, "new_password": "faiblemotdepasse1"},
    )
    assert resp.status_code == 400
