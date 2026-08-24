import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter(prefix="/translate", tags=["Translation"])


class TranslationRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=50)
    target_lang: str = Field(..., pattern="^(EN|DE|IT|ES|PT|RO)$")


def _translate_with_deepl(texts: list[str], target_lang: str) -> list[str]:
    payload = urlencode(
        [("text", text) for text in texts]
        + [("source_lang", "FR"), ("target_lang", target_lang)]
    ).encode("utf-8")
    request = Request(
        settings.DEEPL_API_URL,
        data=payload,
        headers={
            "Authorization": f"DeepL-Auth-Key {settings.DEEPL_API_KEY}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("DeepL translation request failed") from exc
    return [item["text"] for item in data.get("translations", [])]


@router.post("")
async def translate(data: TranslationRequest):
    if not settings.DEEPL_API_KEY:
        raise HTTPException(503, "DeepL n'est pas configuré.")
    if sum(len(text) for text in data.texts) > 10000:
        raise HTTPException(413, "Le contenu à traduire est trop volumineux.")
    try:
        translations = await asyncio.to_thread(
            _translate_with_deepl, data.texts, data.target_lang
        )
    except RuntimeError as exc:
        raise HTTPException(502, "DeepL est momentanément indisponible.") from exc
    if len(translations) != len(data.texts):
        raise HTTPException(502, "Réponse DeepL invalide.")
    return {"translations": translations}