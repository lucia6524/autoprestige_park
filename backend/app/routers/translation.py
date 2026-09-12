import logging
import time
from html import escape as _html_escape
from html import unescape as _html_unescape
from html.parser import HTMLParser

import httpx
from fastapi import APIRouter, HTTPException
from fastapi import Request as StarletteRequest
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/translate", tags=["Translation"])

# Rate limit: max 120 batched translation requests per IP per 5 minutes.
# Le frontend découpe chaque page en blocs HTML (≤9 Ko) ; avec le groupage
# par lots, une page complète tient en quelques requêtes — 120 laissent
# largement la place à une vraie navigation tout en plafonnant l'abus.
_translate_rate_limits: dict[str, list[float]] = {}
_TRANSLATE_RATE_WINDOW = 300
_TRANSLATE_RATE_MAX = 120

# Quota de VOLUME par IP (5 min), en caractères de TEXTE réellement traduits
# (le HTML balancé n'est jamais compté). Les phrases sont groupées par lots
# (≤9 000 caractères) → une page catalogue entière représente ~40 Ko.
_TRANSLATE_VOLUME_WINDOW = 300
_TRANSLATE_VOLUME_MAX = 120_000  # caractères / 5 min / IP

_char_usage: dict[str, list[tuple[float, int]]] = {}

# Endpoint public de Google, utilisé par le widget Google Traduction :
# GRATUIT et sans clé API. Non officiel (pas de SLA) mais stable et massivement
# utilisé. Le frontend met tout en cache (localStorage) → volume réel faible.
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


def _check_translate_rate(ip: str) -> None:
    now = time.time()
    if ip not in _translate_rate_limits:
        _translate_rate_limits[ip] = []
    _translate_rate_limits[ip] = [t for t in _translate_rate_limits[ip] if now - t < _TRANSLATE_RATE_WINDOW]
    if len(_translate_rate_limits[ip]) >= _TRANSLATE_RATE_MAX:
        raise HTTPException(429, "Trop de demandes de traduction. Réessayez plus tard.")
    _translate_rate_limits[ip].append(now)


def _check_translate_volume(ip: str, chars: int) -> None:
    """Plafonne le total de caractères envoyés au provider (évite qu'une seule
    IP n'épuise le quota informel de Google en quelques minutes)."""
    now = time.time()
    history = [(t, c) for t, c in _char_usage.get(ip, []) if now - t < _TRANSLATE_VOLUME_WINDOW]
    total = sum(c for _, c in history) + chars
    if total > _TRANSLATE_VOLUME_MAX:
        raise HTTPException(
            429,
            "Volume de traduction dépassé. Réessayez dans quelques minutes.",
        )
    _char_usage[ip] = history + [(now, chars)]


def _get_ip(req: StarletteRequest) -> str:
    """IP client réelle — délègue au helper partagé (anti-spoofing XFF)."""
    from app.services.rate_limit import get_client_ip
    return get_client_ip(req)


def _raise_provider_error(provider_name: str, exc: httpx.HTTPStatusError) -> HTTPException:
    """Logge le statut/corps RÉEL renvoyé par Google puis lève l'erreur
    HTTP appropriée. Sans ce log, un 502 opaque masque la cause exacte
    (429 à répétition, indisponibilité…)."""
    status = exc.response.status_code
    body = (exc.response.text or "")[:300]
    logger.error("%s rejeté (HTTP %s) : %.300s", provider_name, status, body)
    if status == 429:
        return HTTPException(503, "Quota de traduction momentanément atteint. Réessayez plus tard.")
    if status in (401, 403):
        return HTTPException(502, "Accès au service de traduction refusé.")
    return HTTPException(502, f"{provider_name} est momentanément indisponible.")


def _raise_provider_unavailable(provider_name: str, exc: Exception) -> HTTPException:
    """Échec réseau/timeout vers le provider — loggé pour diagnostic."""
    logger.error("%s injoignable : %s", provider_name, exc)
    return HTTPException(502, f"{provider_name} est momentanément indisponible.")


class TranslationRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=50)
    target_lang: str = Field(..., pattern="^(EN|DE|IT|ES|PT|RO)$")


class HtmlTranslationRequest(BaseModel):
    html: str = Field(..., min_length=1, max_length=120_000)
    target_lang: str = Field(..., pattern="^(EN|DE|IT|ES|PT|RO)$")


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


def _extract_texts_from_html(html: str) -> list[str]:
    """Extrait les nœuds texte d'un fragment HTML, dans l'ordre.

    Ignore `translate="no"` et les balises non traduisibles
    (script, style, textarea…) avec leurs descendants. Chaque occurrence est
    retournée telle quelle (doublons compris) pour permettre le remplacement
    une par une dans le HTML original.
    """
    class TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.texts: list[str] = []
            self.skip_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag in _SKIP_TAGS or dict(attrs).get("translate") == "no":
                self.skip_depth += 1

        def handle_startendtag(self, tag, attrs):
            return

        def handle_endtag(self, tag):
            if self.skip_depth > 0:
                self.skip_depth -= 1

        def handle_data(self, data):
            if self.skip_depth == 0 and data.strip():
                self.texts.append(data)

    parser = TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        raise HTTPException(400, "HTML invalide.") from None
    return parser.texts


# Balises dont le CONTENU ne doit jamais être traduit (ni extrait).
_SKIP_TAGS = {"script", "style", "noscript", "template", "iframe", "svg", "canvas", "textarea"}


def _reinject_translations(html: str, translations: dict[str, str]) -> str:
    """Réinjecte les traductions dans un fragment HTML SANS toucher au markup.

    Contrairement à un `str.replace(text, new, 1)` sur le HTML brut — qui peut
    remplacer la PREMIÈRE occurrence de la chaîne, y compris dans une VALEUR
    D'ATTRIBUT (ex. <a title="Voir les détails">Voir les détails</a> voyait
    son attribut traduit et son texte laissé en français) — cette fonction
    reconstruit le HTML via un parseur :

    - seuls les NŒUDS TEXTE traduisibles sont remplacés ; les attributs
      (title, alt, aria-label, href…) sont réémis à l'identique ;
    - l'appariement utilise le texte DÉCODÉ et NORMALISÉ (entités `&amp;`
      décodées, espaces réduits) : un texte porteur d'entités était jusque-là
      introuvable dans le HTML brut et restait en français ;
    - les nœuds non traduits sont réémis tels quels (entités et espaces
      conservés) ; seuls les nœuds traduits sont rééchappés.
    """
    out: list[str] = []
    # Tampon du nœud texte courant : pièces brutes (réémises telles quelles)
    # + texte décodé accumulé (clé d'appariement). Vidé à chaque balise.
    pending_raw: list[str] = []
    pending_decoded: list[str] = []

    def _flush() -> None:
        if not pending_raw:
            return
        decoded = "".join(pending_decoded)
        norm = " ".join(decoded.split())
        new = translations.get(norm) if norm else None
        if new is not None:
            out.append(_html_escape(new))
        else:
            out.append("".join(pending_raw))
        pending_raw.clear()
        pending_decoded.clear()

    class Reinjector(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.skip_depth = 0

        def _emit_tag(self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool) -> None:
            parts = [f"<{tag}"]
            for name, value in attrs:
                if value is None:
                    parts.append(f" {name}")
                else:
                    parts.append(f' {name}="{_html_escape(value, quote=True)}"')
            parts.append("/>" if self_closing else ">")
            out.append("".join(parts))

        def handle_starttag(self, tag, attrs):
            _flush()
            if tag in _SKIP_TAGS or dict(attrs).get("translate") == "no":
                self.skip_depth += 1
            self._emit_tag(tag, attrs, False)

        def handle_startendtag(self, tag, attrs):
            _flush()
            self._emit_tag(tag, attrs, True)

        def handle_endtag(self, tag):
            _flush()
            if self.skip_depth > 0:
                self.skip_depth -= 1
            out.append(f"</{tag}>")

        def handle_data(self, data):
            if self.skip_depth > 0:
                out.append(data)
                return
            pending_raw.append(data)
            pending_decoded.append(data)

        def handle_entityref(self, name):
            if self.skip_depth > 0:
                out.append(f"&{name};")
                return
            pending_raw.append(f"&{name};")
            pending_decoded.append(_html_unescape(f"&{name};"))

        def handle_charref(self, name):
            if self.skip_depth > 0:
                out.append(f"&#{name};")
                return
            pending_raw.append(f"&#{name};")
            pending_decoded.append(_html_unescape(f"&#{name};"))

        def handle_comment(self, data):
            _flush()
            out.append(f"<!--{data}-->")

        def handle_decl(self, decl):
            _flush()
            out.append(f"<!{decl}>")

        def handle_pi(self, data):
            _flush()
            out.append(f"<?{data}>")

        def unknown_decl(self, data):
            _flush()
            out.append(f"<![{data}]>")

    parser = Reinjector()
    try:
        parser.feed(html)
        parser.close()
        _flush()
    except Exception:
        raise HTTPException(400, "HTML invalide.") from None
    return "".join(out)



@router.post("/html")
async def translate_html(data: HtmlTranslationRequest, request: StarletteRequest):
    """Traduction d'un fragment HTML : les nœuds texte sont extraits, traduits
    (Google gratuit, phrases groupées par lots), puis ré-injectés dans le HTML
    rendu par le navigateur — le style et la structure ne voyagent jamais."""
    _check_translate_rate(_get_ip(request))

    texts = _extract_texts_from_html(data.html)
    if not texts:
        return {"html": data.html}

    # Déduplication avant traduction (même texte en plusieurs endroits = 1 lot).
    unique = list(dict.fromkeys(texts))
    # Le quota de volume compte le TEXTE réellement traduit, jamais le markup.
    _check_translate_volume(_get_ip(request), sum(len(t) for t in unique))

    try:
        translated = await _translate_texts(unique, data.target_lang)
    except httpx.HTTPStatusError as exc:
        raise _raise_provider_error("Google Translate", exc) from exc
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise _raise_provider_unavailable("Google Translate", exc) from exc

    translated_map = {
        " ".join(old.split()): new
        for old, new in zip(unique, translated, strict=False)
        if " ".join(old.split()) != " ".join(new.split())
    }

    if not translated_map:
        return {"html": data.html}
    # Réinjection PARSEUR : seuls les nœuds texte changent, jamais les
    # valeurs d'attributs, et l'appariement tolère les entités HTML.
    return {"html": _reinject_translations(data.html, translated_map)}


@router.post("")
async def translate(data: TranslationRequest, request: StarletteRequest):
    _check_translate_rate(_get_ip(request))
    total_chars = sum(len(text) for text in data.texts)
    if total_chars > 10000:
        raise HTTPException(413, "Le contenu à traduire est trop volumineux.")
    _check_translate_volume(_get_ip(request), total_chars)

    try:
        translations = await _translate_texts(data.texts, data.target_lang)
    except httpx.HTTPStatusError as exc:
        raise _raise_provider_error("Google Translate", exc) from exc
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise _raise_provider_unavailable("Google Translate", exc) from exc

    if len(translations) != len(data.texts):
        raise HTTPException(502, "Réponse Google Translate invalide.")
    return {"translations": translations}
