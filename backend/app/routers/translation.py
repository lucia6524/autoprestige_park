import time

import httpx
from fastapi import APIRouter, HTTPException, Request as StarletteRequest
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter(prefix="/translate", tags=["Translation"])

# Rate limit: max 30 translation requests per IP per 5 minutes
_translate_rate_limits: dict[str, list[float]] = {}
_TRANSLATE_RATE_WINDOW = 300
_TRANSLATE_RATE_MAX = 30


def _check_translate_rate(ip: str) -> None:
    now = time.time()
    if ip not in _translate_rate_limits:
        _translate_rate_limits[ip] = []
    _translate_rate_limits[ip] = [t for t in _translate_rate_limits[ip] if now - t < _TRANSLATE_RATE_WINDOW]
    if len(_translate_rate_limits[ip]) >= _TRANSLATE_RATE_MAX:
        raise HTTPException(429, "Trop de demandes de traduction. Réessayez plus tard.")
    _translate_rate_limits[ip].append(now)


def _get_ip(req: StarletteRequest) -> str:
    forwarded = req.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


class TranslationRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=50)
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
    form_data = [("source_lang", "FR"), ("target_lang", target_lang)]
    for text in texts:
        form_data.append(("text", text))

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            settings.DEEPL_API_URL,
            data=form_data,
            headers={
                "Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return [item["text"] for item in data.get("translations", [])]


@router.post("")
async def translate(data: TranslationRequest, request: StarletteRequest):
    _check_translate_rate(_get_ip(request))
    if sum(len(text) for text in data.texts) > 10000:
        raise HTTPException(413, "Le contenu à traduire est trop volumineux.")

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
        status = exc.response.status_code
        if status == 429:
            raise HTTPException(503, "Quota de traduction atteint. Réessayez plus tard.") from exc
        if status in (401, 403):
            raise HTTPException(502, "Clé API de traduction invalide ou non activée.") from exc
        raise HTTPException(502, f"{provider_name} est momentanément indisponible.") from exc
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise HTTPException(502, f"{provider_name} est momentanément indisponible.") from exc

    if len(translations) != len(data.texts):
        raise HTTPException(502, f"Réponse {provider_name} invalide.")
    return {"translations": translations}