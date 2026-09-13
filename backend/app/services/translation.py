"""Moteur de traduction FR→X (Google endpoint public gratuit).

Ce module est le moteur partagé des SCRIPTS OPÉRATEUR :
  - pretranslate_vehicles.py : pré-traduction des descriptions du catalogue
    (colonnes description_<lang>, usage in-process) ;
  - backfill_translations_api.py : backfill via l'API admin (import tardif).

Il n'y a plus d'endpoint HTTP /api/translate : la traduction du SITE est
assurée côté navigateur par le widget GTranslate (voir frontend/src/layouts/
Layout.astro). Le moteur reste ici uniquement pour la traduction one-shot
des données (backoff, lots ≤ 40 phrases / 9 000 caractères inclus).
"""

import logging

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Endpoint public de Google, utilisé par le widget Google Traduction :
# GRATUIT et sans clé API. Non officiel (pas de SLA) mais stable et massivement
# utilisé.
GOOGLE_FREE_API_URL = "https://translate.google.com/translate_a/t"

# Groupage : jusqu'à 40 phrases (ou 9 000 caractères) par appel Google,
# séparées par des retours à la ligne. Google renvoie une réponse avec le
# MÊME nombre de lignes → 1 appel peut traduire un lot complet de phrases.
_FREE_BATCH_MAX_ITEMS = 40
_FREE_BATCH_MAX_CHARS = 9_000
# Délai imposé entre deux LOTS : l'endpoint est sensible au « trop fréquent ».
_FREE_DELAY_BETWEEN = 0.35
_FREE_RETRY_BACKOFF = [1.0, 3.0, 8.0]


def _coerce_translated_string(data_first) -> str:
    """Extrait la chaîne traduite de la réponse Google.

    Le format usuel (client=gtx, dt=t) renvoie CHAQUE segment de traduction
    concaténé en une seule chaîne (les retours à la ligne internes des phrases
    sont conservés). Certains dumps renvoient une liste de segments
    `[[texte_traduit, texte_source, ...], ...]` — on la concatène alors par
    retours à la ligne pour retomber sur le même format.
    """
    if isinstance(data_first, str):
        return data_first
    parts: list[str] = []
    if isinstance(data_first, list):
        for seg in data_first:
            if isinstance(seg, list) and seg and isinstance(seg[0], str):
                parts.append(seg[0])
    return "\n".join(parts)


async def _translate_google_free_batch(texts: list[str], target_lang: str) -> list[str]:
    """Traduit UN LOT de phrases via l'endpoint public gratuit de Google.

    Les phrases sont concaténées par retour à la ligne et envoyées en UN seul
    appel : Google renvoie la traduction avec le même nombre de lignes.
    Retourne une liste de traductions, dans l'ordre. Lève HTTPStatusError /
    HTTPError (traduites en 502/503 par l'appelant) ou HTTPException 502 si la
    réponse n'est pas découpable en autant de lignes qu'attendu.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Content-Length": "0",
    }
    payload = "\n".join(texts)
    last_error: Exception | None = None
    for attempt, wait in enumerate([0, *_FREE_RETRY_BACKOFF]):
        if attempt:
            await _sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    GOOGLE_FREE_API_URL,
                    params={"client": "gtx", "sl": "fr", "tl": target_lang.lower(), "dt": "t", "q": payload},
                    headers=headers,
                )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                raise HTTPException(502, "Réponse Google invalide.")
            translated_str = _coerce_translated_string(data[0])
            if len(texts) == 1:
                # Phrase isolée (très souvent multi-lignes, ex. nœuds texte du
                # HTML) : la réponse ENTIÈRE est sa traduction. Découper par
                # `\n` rendrait un nombre de lignes ≠ nombre de phrases dès
                # que Google conserve les retours à la ligne internes → 502.
                # On renvoie donc le bloc complet tel quel.
                return [translated_str or texts[0]]
            translated = translated_str.split("\n")
            if len(translated) != len(texts):
                raise HTTPException(502, "Réponse Google invalide.")
            return translated
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response.status_code == 429:
                # Google nous demande de ralentir : on retente après backoff.
                continue
            raise
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_error = exc
            continue
    if isinstance(last_error, httpx.HTTPStatusError):
        raise last_error
    raise last_error  # type: ignore[misc]


async def _translate_google_free(text: str, target_lang: str) -> str:
    """Traduit UNE phrase (repli : lot d'une seule phrase)."""
    return (await _translate_google_free_batch([text], target_lang))[0]


async def _translate_texts(texts: list[str], target_lang: str) -> list[str]:
    """Traduit une liste de phrases FR→target, groupées par LOTS.

    Jusqu'à 40 phrases (≤9 000 caractères) par appel Google : une page
    complète tient en quelques appels au lieu d'un appel par phrase.
    Repli : 1 appel par phrase si la réponse du lot n'est pas découpable ;
    les phrases contenant un retour à la ligne sont envoyées seules.
    """
    result: list[str] = [""] * len(texts)
    pending: list[str] = []
    pending_idx: list[int] = []
    pending_chars = 0

    async def _flush() -> None:
        nonlocal pending, pending_idx, pending_chars
        if not pending:
            return
        batch, idxs = pending, pending_idx
        try:
            translated = await _translate_google_free_batch(batch, target_lang)
            for pos, idx in enumerate(idxs):
                result[idx] = translated[pos]
        except HTTPException:
            # Réponse Google non découpable : repli 1 appel par phrase.
            for pos, idx in enumerate(idxs):
                result[idx] = await _translate_google_free(batch[pos], target_lang)
        pending, pending_idx, pending_chars = [], [], 0

    for i, text in enumerate(texts):
        if "\n" in text:
            await _flush()
            result[i] = await _translate_google_free(text, target_lang)
            continue
        if (
            pending
            and (
                len(pending) >= _FREE_BATCH_MAX_ITEMS
                or pending_chars + len(text) > _FREE_BATCH_MAX_CHARS
            )
        ):
            await _flush()
            await _sleep(_FREE_DELAY_BETWEEN)
        pending.append(text)
        pending_idx.append(i)
        pending_chars += len(text)
    await _flush()
    return result


async def _sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)
