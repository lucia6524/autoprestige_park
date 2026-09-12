"""Régression sécurité : middleware taille de corps et extraction d'IP cliente."""
from starlette.requests import Request

from app.config import settings
from app.services import rate_limit


def _make_request(headers: dict[str, str], client_host: str = "10.0.0.5") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/auth/login",
        "client": (client_host, 4321),
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in headers.items()
        ],
    }
    return Request(scope)


def test_client_ip_uses_last_xff_hop_in_production(monkeypatch):
    """La limite par IP doit être clé sur le DERNIER saut XFF (après Render),
    jamais sur une valeur forgée par le client en tête de liste."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    req = _make_request({"X-Forwarded-For": "8.8.8.8, 203.0.113.7"})

    ip = rate_limit.get_client_ip(req)

    # Une liste [spoofée, réelle] → on garde 203.0.113.7, pas 8.8.8.8.
    assert ip == "203.0.113.7"


def test_client_ip_spoofed_first_hop_ignored(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    req = _make_request(
        {"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 3.3.3.3, 198.51.100.9"}
    )
    assert rate_limit.get_client_ip(req) == "198.51.100.9"

    # Cas simple sans liste : une seule entrée = l'IP de l'edge.
    req2 = _make_request({"X-Forwarded-For": "198.51.100.9"})
    assert rate_limit.get_client_ip(req2) == "198.51.100.9"


def test_client_ip_ignores_xff_in_plain_dev():
    """En dev direct (pas derrière un proxy de confiance), l'en-tête forgé
    est ignoré et on tombe sur l'IP du socket."""
    req = _make_request({"X-Forwarded-For": "8.8.8.8"}, client_host="127.0.0.1")
    req_direct = _make_request(
        {"X-Forwarded-For": "8.8.8.8, 9.9.9.9"}, client_host="203.0.113.50"
    )

    # Dev derrière un proxy local (loopback) : dernier saut accepté.
    assert rate_limit.get_client_ip(req) == "8.8.8.8"
    # Dev direct : l'en-tête est falsifiable → IP du peer.
    assert rate_limit.get_client_ip(req_direct) == "203.0.113.50"


async def test_mutation_without_content_length_rejected(client):
    """Un corps envoyé en chunked (sans Content-Length) ne doit pas passer :
    la limite 8 Mo se contourner via l'absence de Content-Length."""
    resp = await client.post(
        "/api/auth/login",
        headers={"transfer-encoding": "chunked"},
        content=b"x" * 4096,
    )
    assert resp.status_code == 413
