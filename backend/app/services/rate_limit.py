"""Rate limiting en mémoire, partagé par tous les routers.

Fenêtre glissante par IP. Adapté au déploiement Render actuel (1 worker) ;
si l'API passe en multi-worker / multi-instance, migrer ce stockage vers Redis
ou une table en base (l'interface check(ip, scope) reste identique).
"""
import logging
import time

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Fenêtre par défaut : 5 minutes
WINDOW_SECONDS = 300

# Scopes indépendants : chaque endpoint a son propre compteur.
# (fenêtre, max requêtes)
LIMITS: dict[str, tuple[int, int]] = {
    "contact": (WINDOW_SECONDS, 5),         # 5 messages / 5 min / IP
    "review_submit": (WINDOW_SECONDS, 3),   # 3 avis / 5 min / IP
    "sell_request": (WINDOW_SECONDS, 3),    # 3 demandes / 5 min / IP
    # Codes OTP par email (clé "email:<adresse>") : 5 / heure. Appliqué AVANT
    # la vérification d'existence du compte — sinon le 429 lui-même trahirait
    # quels emails sont inscrits.
    "otp_code": (3600, 5),
    # Tentatives de connexion par email (clé "email:<adresse>") : 15 / 15 min.
    # Complète la limite par IP : bloque le brute-force distribué (plusieurs
    # IPs) contre un compte ciblé. Appliqué avant la recherche du compte pour
    # que le 429 ne révèle pas l'existence de l'email.
    "login_email": (900, 15),
    # Génération de codes OTP (login/request-code, register/step3) : 15 / 5 min
    # / IP, en plus de la limite par email — coupe le « mail-bombing » qui
    # viserait des adresses distinctes depuis une même IP.
    "otp_generate": (WINDOW_SECONDS, 15),
    # Vérification du code d'inscription : 10 / 5 min / IP (anti brute-force OTP).
    "register_verify": (WINDOW_SECONDS, 10),
    # Finalisation du mot de passe : 10 / 5 min / IP (anti force brute/abuse).
    "register_set_password": (WINDOW_SECONDS, 10),
}

_buckets: dict[str, list[float]] = {}


def get_client_ip(request: Request) -> str:
    """IP client réelle derrière le proxy Render.

    Render transmet l'IP d'origine dans X-Forwarded-For. En dev local, on
    retombe sur request.client.host. Uniquement la première IP de la liste :
    les suivantes sont contrôlées par l'infrastructure, pas par le client.

    ⚠️ Règle anti-spoofing corrigée : sur Render, la connexion entre le proxy
    et uvicorn vient d'une IP privée interne (pas loopback) — la vérification
    « loopback only » faisait retomber TOUS les visiteurs sur l'IP du proxy
    (un seul bucket de rate-limit pour tout le site). En production, Render
    est l'unique point d'entrée et écrase l'en-tête : la première entrée XFF
    est fiable. En dev, on ne la lit que derrière un proxy local (loopback).
    """
    from app.config import settings

    client_host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return client_host
    first_hop = forwarded.split(",")[0].strip()
    trusted = settings.ENVIRONMENT.lower() == "production" or client_host in (
        "127.0.0.1", "::1", "localhost",
    )
    if trusted:
        return first_hop or client_host
    # Dev direct (IP publique) : l'en-tête est falsifiable → on l'ignore.
    return client_host


def check_rate_limit(scope: str, ip: str) -> None:
    """Lève HTTP 429 si l'IP dépasse la limite du scope."""
    window, max_requests = LIMITS.get(scope, (WINDOW_SECONDS, 10))
    key = f"{scope}:{ip}"
    now = time.time()

    bucket = [t for t in _buckets.get(key, []) if now - t < window]
    if len(bucket) >= max_requests:
        logger.warning("Rate limit atteint — scope=%s ip=%s (%d/%d)", scope, ip, len(bucket), max_requests)
        raise HTTPException(
            429,
            f"Trop de demandes. Réessayez dans quelques minutes "
            f"(max {max_requests} par {window // 60} minutes).",
        )
    bucket.append(now)
    _buckets[key] = bucket

    # Nettoyage périodique des clés inactives (évite la croissance mémoire)
    if len(_buckets) > 10_000:
        cutoff = now - window
        for k in list(_buckets.keys()):
            _buckets[k] = [t for t in _buckets[k] if t >= cutoff]
            if not _buckets[k]:
                del _buckets[k]
