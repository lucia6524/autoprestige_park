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

    X-Forwarded-For est une liste où chaque proxy AJOUTE l'IP qu'il reçoit à la
    FIN. Le client ne peut forger que les valeurs de TÊTE de liste — jamais la
    dernière (ajoutée par l'edge Render, point d'entrée unique). Un attaquant
    qui injecte `X-Forwarded-For: 8.8.8.1` ferait donc uniquement grossir les
    valeurs de tête : on lit le DERNIER saut (la vraie IP du visiteur).

    ⚠️ Lien avec la faille corrigée : le code prenait le PREMIER saut. Le site
    est en production derrière Render, qui ne remplace pas l'en-tête mais le
    lit tel quel (constaté en prod : une valeur forgée était bien comptée). La
    règle « première entrée = fiable » était donc contournable d'une seule
    machine en changeant l'IP à chaque requête (tous les rate-limits IP
    neutralisés). Le dernier saut ne peut être altéré par le client.

    En dev direct (Python lancé en local, sans proxy), l'en-tête est
    falsifiable et uvicorn n'est derrière aucun edge fiable → on l'ignore et
    on retombe sur request.client.host. En dev derrière un proxy local
    (uvicorn --proxy-headers, loopback), on lit le même dernier saut.
    """
    from app.config import settings

    client_host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return client_host
    trusted = settings.ENVIRONMENT.lower() == "production" or client_host in (
        "127.0.0.1", "::1", "localhost",
    )
    if not trusted:
        # Dev direct (IP publique) : l'en-tête est falsifiable → on l'ignore.
        return client_host
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    return hops[-1] or client_host


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
