"""Rate limiting en mémoire, partagé par tous les routers.

Fenêtre glissante par IP. Adapté au déploiement Render actuel (1 worker) ;
si l'API passe en multi-worker / multi-instance, migrer ce stockage vers Redis
ou une table en base (l'interface check(ip, scope) reste identique).
"""
import time
from typing import Dict, List, Tuple

from fastapi import HTTPException, Request

# Fenêtre par défaut : 5 minutes
WINDOW_SECONDS = 300

# Scopes indépendants : chaque endpoint a son propre compteur.
# (fenêtre, max requêtes)
LIMITS: Dict[str, Tuple[int, int]] = {
    "contact": (WINDOW_SECONDS, 5),         # 5 messages / 5 min / IP
    "review_submit": (WINDOW_SECONDS, 3),   # 3 avis / 5 min / IP
    "sell_request": (WINDOW_SECONDS, 3),    # 3 demandes / 5 min / IP
    # Codes OTP par email (clé "email:<adresse>") : 5 / heure. Appliqué AVANT
    # la vérification d'existence du compte — sinon le 429 lui-même trahirait
    # quels emails sont inscrits.
    "otp_code": (3600, 5),
}

_buckets: Dict[str, List[float]] = {}


def get_client_ip(request: Request) -> str:
    """IP client réelle derrière le proxy Render.

    Render transmet l'IP d'origine dans X-Forwarded-For. En dev local, on
    retombe sur request.client.host. Uniquement la première IP de la liste :
    les suivantes sont contrôlées par l'infrastructure, pas par le client.
    """
    client_host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return client_host
    first_hop = forwarded.split(",")[0].strip()
    # Anti-spoofing basique : ne faire confiance à l'en-tête que si la
    # connexion vient d'un relais interne (loopback = proxy Render en prod).
    # En dev direct (IP publique), l'en-tête est falsifiable → on l'ignore.
    if client_host in ("127.0.0.1", "::1", "localhost"):
        return first_hop or client_host
    return client_host


def check_rate_limit(scope: str, ip: str) -> None:
    """Lève HTTP 429 si l'IP dépasse la limite du scope."""
    window, max_requests = LIMITS.get(scope, (WINDOW_SECONDS, 10))
    key = f"{scope}:{ip}"
    now = time.time()

    bucket = [t for t in _buckets.get(key, []) if now - t < window]
    if len(bucket) >= max_requests:
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
