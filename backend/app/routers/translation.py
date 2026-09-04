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
    if not settings.DEEPL_API_KEY:
        raise HTTPException(503, "DeepL n'est pas configuré.")
    if sum(len(text) for text in data.texts) > 10000:
        raise HTTPException(413, "Le contenu à traduire est trop volumineux.")
    try:
        translations = await _translate_with_deepl(data.texts, data.target_lang)
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        raise HTTPException(502, "DeepL est momentanément indisponible.") from exc
    if len(translations) != len(data.texts):
        raise HTTPException(502, "Réponse DeepL invalide.")
    return {"translations": translations}