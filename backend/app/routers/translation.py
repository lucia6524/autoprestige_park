import logging
import time

import httpx
from fastapi import APIRouter, HTTPException
from fastapi import Request as StarletteRequest
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/translate", tags=["Translation"])

# Rate limit: max 120 batched translation requests per IP per 5 minutes.
# Le frontend regroupe ~40 phrases par requête : une page complète tient en
# 1 à 3 requêtes, donc 120 laissent largement la place à une vraie navigation
# tout en plafonnant l'abus du quota DeepL.
_translate_rate_limits: dict[str, list[float]] = {}
_TRANSLATE_RATE_WINDOW = 300
_TRANSLATE_RATE_MAX = 120

# Quota de VOLUME par IP (5 min) : 120 requêtes × 120 Ko autoriseraient ~14 M
# de caractères / 5 min — de quoi épuiser le quota mensuel DeepL (500 k chars
# gratuit) en quelques minutes. On plafonne donc le total de caractères envoyés.
_TRANSLATE_VOLUME_WINDOW = 300
_TRANSLATE_VOLUME_MAX = 60_000  # caractères / 5 min / IP

_char_usage: dict[str, list[tuple[float, int]]] = {}


def _check_translate_rate(ip: str) -> None:
    now = time.time()
    if ip not in _translate_rate_limits:
        _translate_rate_limits[ip] = []
    _translate_rate_limits[ip] = [t for t in _translate_rate_limits[ip] if now - t < _TRANSLATE_RATE_WINDOW]
    if len(_translate_rate_limits[ip]) >= _TRANSLATE_RATE_MAX:
        raise HTTPException(429, "Trop de demandes de traduction. Réessayez plus tard.")
    _translate_rate_limits[ip].append(now)


def _check_translate_volume(ip: str, chars: int) -> None:
    """Plafonne le total de caractères envoyés au provider (quota), pas juste
    le nombre de requêtes : 120 requêtes × 120 Ko épuiseraient DeepL gratuit en
    quelques minutes (500 k caractères/mois)."""
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
    """Logge le statut/corps RÉEL renvoyé par le provider puis lève l'erreur
    HTTP appropriée. Sans ce log, un 502 opaque masque la cause exacte
    (clé invalide 401/403, quota 456, quota temporaire 429, indisponibilité)."""
    status = exc.response.status_code
    body = (exc.response.text or "")[:300]
    logger.error("%s rejeté (HTTP %s) : %.300s", provider_name, status, body)
    if status == 429:
        return HTTPException(503, "Quota de traduction atteint. Réessayez plus tard.")
    if status == 456:  # DeepL : quota mensuel épuisé (implémentation gratuite)
        return HTTPException(503, "Quota mensuel de traduction atteint. Revenez le mois prochain.")
    if status in (401, 403):
        return HTTPException(502, "Clé API de traduction invalide ou non activée.")
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


async def _translate_with_google(texts: list[str], target_lang: str) -> list[str]:
    """Async Google Cloud Translation v2 via httpx — API key auth."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            settings.GOOGLE_TRANSLATE_API_URL,
            headers={"x-goog-api-key": settings.GOOGLE_TRANSLATE_API_KEY},
            json={
                "q": texts,
                "source": "fr",
                "target": target_lang.lower(),
                # "text" évite que Google échappe les entités HTML (&amp; etc.)
                "format": "text",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    translations = data.get("data", {}).get("translations", [])
    return [item.get("translatedText", "") for item in translations]


async def _translate_with_deepl(texts: list[str], target_lang: str) -> list[str]:
    """Async DeepL translation via httpx — no thread blocking."""
    # DeepL exige une variante régionale pour le portugais : le site utilise
    # le portugais européen (locales/pt.json), donc PT-PT.
    deepl_target = "PT-PT" if target_lang.upper() == "PT" else target_lang
    # Corps JSON (accepté par DeepL v2) — évite la régression httpx 0.28 sur
    # les requêtes x-www-form-urlencoded avec AsyncClient.
    payload = {
        "text": texts,
        "source_lang": "FR",
        "target_lang": deepl_target,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            settings.DEEPL_API_URL,
            json=payload,
            headers={
                "Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return [item["text"] for item in data.get("translations", [])]


def _sanitize_fragment_for_translation(html: str) -> str:
    """Nettoie un fragment HTML avant l'envoi à DeepL.

    Étape 4 du protocole : un HTML malformé fait ignorer des blocs entiers par
    DeepL. On retire donc scripts/styles, éléments non traduisibles, attributs
    d'événement, et on garantit une racine unique — seule structure qu'une
    réponse HTML de DeepL est garantie de préserver.
    """
    from html.parser import HTMLParser

    void_elements = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
    skip_tags = {"script", "style", "noscript", "template", "iframe", "svg", "canvas"}

    class Cleaner(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out: list[str] = []
            self.stack: list[str] = []
            self.skip_depth = 0

        def handle_starttag(self, tag, attrs):
            attrs_dict = dict(attrs)
            if tag in skip_tags or attrs_dict.get("translate") == "no":
                if tag in void_elements:
                    return
                if self.skip_depth == 0:
                    self.skip_depth = 1
                else:
                    self.skip_depth += 1
                self.stack.append(tag)
                return
            if self.skip_depth > 0:
                self.stack.append(tag)
                self.skip_depth += 1
                return
            self.out.append(self._emit(tag, attrs, void_elements))
            if tag not in void_elements:
                self.stack.append(tag)

        def handle_startendtag(self, tag, attrs):
            if self.skip_depth > 0:
                return
            self.out.append(self._emit(tag, attrs, void_elements))

        def handle_endtag(self, tag):
            if tag in void_elements:
                return
            if self.skip_depth > 0:
                if self.stack:
                    self.stack.pop()
                self.skip_depth -= 1
                return
            if tag in skip_tags:
                return
            if tag in self.stack:
                while self.stack:
                    if self.stack.pop() == tag:
                        break
            self.out.append(f"</{tag}>")

        def handle_data(self, data):
            if self.skip_depth == 0:
                self.out.append(data)

        @staticmethod
        def _emit(tag, attrs, void_elements):
            kept = []
            for name, value in attrs:
                if value is None:
                    kept.append(name)
                    continue
                # Attributs d'événement/JS retirés (sécurité + propreté DeepL)
                if name.lower().startswith("on") or name == "srcset":
                    continue
                kept.append(f'{name}="{value}"')
            attr_str = (" " + " ".join(kept)) if kept else ""
            if tag in void_elements:
                return f"<{tag}{attr_str}>"
            return f"<{tag}{attr_str}>"

    parser = Cleaner()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        raise HTTPException(400, "HTML invalide.") from None
    body = "".join(parser.out).strip()
    if not body:
        return ""
    # Racine unique : DeepL HTML v2 garantit la structure pour UN document.
    return f"<div>{body}</div>"


def _restore_translated_fragment(raw: str, cleaned: str, original_html: str) -> str:
    """Remplace les textes du HTML original par la version traduite.

    La réponse de DeepL est un document reformaté ; on n'insère donc JAMAIS
    son HTML tel quel. On appaire chaque texte traduit au texte du fragment
    NETTOYÉ (exactement ce qui a été envoyé), puis on remplace ce texte dans
    le HTML original : attributs, images, inputs et structure du client sont
    intégralement conservés.
    """
    from html.parser import HTMLParser

    class TextCollector(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.chunks: list[str] = []

        def handle_data(self, data):
            if data.strip():
                self.chunks.append(data)

    try:
        collector = TextCollector()
        collector.feed(raw)
        collector.close()
        sent = TextCollector()
        sent.feed(cleaned)
        sent.close()
    except Exception:
        return original_html  # réponse illisible → fragment original intact

    texts = collector.chunks
    if not texts or len(texts) != len(sent.chunks):
        return original_html  # structure inattendue → on ne casse rien

    result = original_html
    for old, new in zip(sent.chunks, texts, strict=False):
        if " ".join(old.split()) != " ".join(new.split()):
            result = result.replace(old, new, 1)
    return result


@router.post("/html")
async def translate_html(data: HtmlTranslationRequest, request: StarletteRequest):
    """Traduction d'un fragment HTML entier (tag_handling=html, v2).

    Le fragment est nettoyé (scripts/styles/translate=no retirés), envoyé en
    UNE requête DeepL, puis les textes traduits sont réinjectés dans le HTML
    original du client — seuls les textes voyagent, jamais la structure.
    """
    _check_translate_rate(_get_ip(request))
    _check_translate_volume(_get_ip(request), len(data.html))

    cleaned = _sanitize_fragment_for_translation(data.html)
    if not cleaned:
        return {"html": data.html}

    provider_name = "DeepL"
    if settings.TRANSLATION_PROVIDER == "deepl":
        if not settings.DEEPL_API_KEY:
            raise HTTPException(503, "DeepL n'est pas configuré.")

        deepl_target = "PT-PT" if data.target_lang.upper() == "PT" else data.target_lang
        payload = {
            "text": [cleaned],
            "source_lang": "FR",
            "target_lang": deepl_target,
            # Étapes 1 & 2 du protocole : mode HTML v2, document envoyé entier.
            "tag_handling": "html",
            "tag_handling_version": "v2",
            "ignore_tags": "script,style",  # défensif : s'ajoute à translate=no
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    settings.DEEPL_API_URL,
                    json=payload,
                    headers={"Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}"},
                )
                resp.raise_for_status()
                data_deepl = resp.json()
        except httpx.HTTPStatusError as exc:
            raise _raise_provider_error(provider_name, exc) from exc
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise _raise_provider_unavailable(provider_name, exc) from exc

        translations = data_deepl.get("translations", [])
        if not translations or not isinstance(translations[0].get("text"), str):
            raise HTTPException(502, f"Réponse {provider_name} invalide.")
        raw = translations[0]["text"]
    else:
        # Repli Google : collecte des nœuds texte du fragment nettoyé.
        from html.parser import HTMLParser

        class _TextOnly(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.texts: list[str] = []

            def handle_data(self, data):
                if data.strip():
                    self.texts.append(data)

        parser = _TextOnly()
        try:
            parser.feed(cleaned)
            parser.close()
        except Exception:
            raise HTTPException(400, "HTML invalide.") from None
        if not parser.texts:
            return {"html": data.html}
        try:
            translated_texts = await _translate_with_google(parser.texts, data.target_lang)
        except httpx.HTTPStatusError as exc:
            raise _raise_provider_error("Google Translate", exc) from exc
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise _raise_provider_unavailable("Google Translate", exc) from exc
        # Ré-injection : remplace les textes du fragment original.
        result = data.html
        for old, new in zip(parser.texts, translated_texts, strict=False):
            if " ".join(old.split()) != " ".join(new.split()):
                result = result.replace(old, new, 1)
        return {"html": result}

    return {"html": _restore_translated_fragment(raw, cleaned, data.html)}


@router.post("")
async def translate(data: TranslationRequest, request: StarletteRequest):
    _check_translate_rate(_get_ip(request))
    total_chars = sum(len(text) for text in data.texts)
    if total_chars > 10000:
        raise HTTPException(413, "Le contenu à traduire est trop volumineux.")
    _check_translate_volume(_get_ip(request), total_chars)

    if settings.TRANSLATION_PROVIDER == "deepl":
        if not settings.DEEPL_API_KEY:
            raise HTTPException(503, "DeepL n'est pas configuré.")
        provider_name = "DeepL"
        translate_func = _translate_with_deepl
    else:
        if not settings.GOOGLE_TRANSLATE_API_KEY:
            raise HTTPException(503, "Google Translate n'est pas configuré.")
        provider_name = "Google Translate"
        translate_func = _translate_with_google

    try:
        translations = await translate_func(data.texts, data.target_lang)
    except httpx.HTTPStatusError as exc:
        raise _raise_provider_error(provider_name, exc) from exc
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise _raise_provider_unavailable(provider_name, exc) from exc

    if len(translations) != len(data.texts):
        raise HTTPException(502, f"Réponse {provider_name} invalide.")
    return {"translations": translations}
