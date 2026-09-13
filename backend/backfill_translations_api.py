"""Backfill des descriptions pré-traduites VIA L'API ADMIN (pas d'accès DB direct).

Utile quand on n'a pas l'URL PostgreSQL mais seulement les identifiants admin :
- lit le catalogue via GET /api/admin/vehicles,
- traduit les descriptions manquantes (DeepL si clé dispo, sinon le traducteur
  Google intégré au projet — celui du runtime),
- écrit via PATCH /api/admin/vehicles/{id} (champs description_<lang>).

Idempotent et reprenable : un véhicule dont la colonne cible est déjà remplie
est ignoré. `--force` retraduit tout (ex. repasser en DeepL après reset quota).

Usage:
    ADMIN_EMAIL=... ADMIN_PASSWORD=... python backfill_translations_api.py \
        --api https://autohaus-park-api.onrender.com/api --lang en,de [--provider google] [--force]
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

DEEPL_URL_DEFAULT = "https://api-free.deepl.com/v2/translate"
DEEPL_TARGET = {"en": "EN", "de": "DE", "it": "IT", "es": "ES", "pt": "PT", "ro": "RO"}
LANGS = tuple(DEEPL_TARGET)
BATCH = 40  # DeepL : jusqu'à 50 textes par requête ; Google pipeline : 40 aussi
DELAY_PATCH = 0.3  # politesse entre deux PATCH admin


def load_env_value(name: str, default: str = "") -> str:
    if os.getenv(name):
        return os.getenv(name, default)
    env_file = BACKEND_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return default


def deepl_translate(client: httpx.Client, key: str, url: str, texts: list[str], target: str) -> list[str]:
    """Traduit un lot via DeepL avec retries (429/5xx/réseau). Lève sur 456 (quota)."""
    for attempt in range(4):
        try:
            r = client.post(
                url,
                headers={"Authorization": f"DeepL-Auth-Key {key}"},
                json={"text": texts, "target_lang": target},
            )
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 5 * (attempt + 1)))
                print(f"    ⏳ 429 DeepL, pause {wait}s…")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return [t["text"] for t in r.json()["translations"]]
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if attempt == 3:
                raise
            print(f"    ⚠️ réseau DeepL ({e.__class__.__name__}), retry {attempt + 2}/4…")
            time.sleep(2 * (attempt + 1))
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500 and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise RuntimeError("DeepL injoignable après retries")


def google_translate(texts: list[str], target_lang: str) -> list[str]:
    """Traduit via le moteur du projet (app.services.translation, backoff inclus)."""
    from app.services.translation import _translate_texts

    return asyncio.run(_translate_texts(texts, target_lang.upper()))


def admin_patch(client: httpx.Client, api: str, headers: dict, vid: int, payload: dict) -> bool:
    for attempt in range(3):
        try:
            r = client.patch(f"{api}/admin/vehicles/{vid}", headers=headers, json=payload)
            if r.status_code == 200:
                return True
            print(f"    ❌ PATCH #{vid} → {r.status_code} : {r.text[:120]}")
            return False
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == 2:
                print(f"    ❌ PATCH #{vid} : réseau après retries")
                return False
            time.sleep(2 * (attempt + 1))
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill traductions via API admin.")
    parser.add_argument("--api", default="https://autohaus-park-api.onrender.com/api")
    parser.add_argument("--email", default=os.getenv("ADMIN_EMAIL", ""))
    parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD", ""))
    parser.add_argument("--lang", default=",".join(LANGS), help="ex: en,de")
    parser.add_argument("--provider", choices=("auto", "deepl", "google"), default="auto",
                        help="auto : DeepL si clé, bascule Google si quota épuisé (456)")
    parser.add_argument("--force", action="store_true",
                        help="retraduit même les colonnes déjà remplies (ex. repassage DeepL)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.email or not args.password:
        sys.exit("Identifiants admin requis (--email/--password ou ADMIN_EMAIL/ADMIN_PASSWORD).")
    langs = [lg.strip().lower() for lg in args.lang.split(",") if lg.strip()]
    bad = [lg for lg in langs if lg not in LANGS]
    if bad:
        sys.exit(f"Langues inconnues : {bad} (supportées : {LANGS})")

    deepl_key = load_env_value("DEEPL_API_KEY")
    deepl_url = load_env_value("DEEPL_API_URL", DEEPL_URL_DEFAULT)
    provider = args.provider
    if provider == "deepl" and not deepl_key:
        sys.exit("--provider deepl : clé DEEPL_API_KEY introuvable.")
    if provider == "auto" and not deepl_key:
        provider = "google"
    print(f"🔬 Provider : {provider}")

    client = httpx.Client(timeout=90)

    print("🔑 Login admin…")
    r = client.post(f"{args.api}/auth/login", json={"email": args.email, "password": args.password})
    if r.status_code != 200:
        sys.exit(f"❌ Login échoué ({r.status_code}) : {r.text[:200]}")
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    print("✅ Connecté")

    print("📋 Récupération du catalogue…")
    r = client.get(f"{args.api}/admin/vehicles", headers=headers, params={"limit": 200})
    if r.status_code != 200:
        sys.exit(f"❌ Listing échoué ({r.status_code}) : {r.text[:200]}")
    vehicles = r.json()
    if not vehicles:
        sys.exit("❌ Aucun véhicule en base — lance d'abord import_vehicles.py.")
    if "description_en" not in vehicles[0]:
        sys.exit("❌ L'API n'expose pas description_* — redéploiement Render pas encore passé.")
    print(f"✅ {len(vehicles)} véhicules")

    written_totals = {}
    for lang in langs:
        if args.force:
            targets = [v for v in vehicles if v["description"].strip()]
        else:
            targets = [
                v for v in vehicles
                if v["description"].strip() and not (v.get(f"description_{lang}") or "").strip()
            ]
        print(f"\n── {lang.upper()} : {len(targets)} à traduire ──")
        if not targets:
            print("  ✅ déjà traduit")
            continue
        if args.dry_run:
            continue

        ok = 0
        for i in range(0, len(targets), BATCH):
            chunk = targets[i : i + BATCH]
            texts = [v["description"] for v in chunk]
            try:
                if provider == "deepl":
                    translated = deepl_translate(client, deepl_key, deepl_url, texts, DEEPL_TARGET[lang])
                else:
                    translated = google_translate(texts, lang)
            except httpx.HTTPStatusError as e:
                if provider in ("auto", "deepl") and e.response.status_code == 456:
                    print("  ⚠️ Quota DeepL épuisé (456) → bascule sur Google pour la suite.")
                    provider = "google"
                    try:
                        translated = google_translate(texts, lang)
                    except Exception as e2:
                        print(f"  ❌ lot {i // BATCH + 1} : {e2} — reprise possible")
                        continue
                else:
                    print(f"  ❌ lot {i // BATCH + 1} : {e} — reprise possible")
                    continue
            except Exception as e:
                print(f"  ❌ lot {i // BATCH + 1} : {e} — reprise possible")
                continue

            for v, tr in zip(chunk, translated, strict=False):
                if admin_patch(client, args.api, headers, v["id"], {f"description_{lang}": tr}):
                    ok += 1
                time.sleep(DELAY_PATCH)
            print(f"  ➕ lot {i // BATCH + 1}/{(len(targets) + BATCH - 1) // BATCH} : {len(chunk)} traduits")

        written_totals[lang] = ok
        print(f"  ✅ {lang.upper()} : {ok}/{len(targets)} écrits")

    print("\n" + "=" * 50)
    print("Écrits :", json.dumps(written_totals, ensure_ascii=False),
          f"(provider final : {provider})")
    if args.dry_run:
        print("(dry-run : rien n'a été écrit)")


if __name__ == "__main__":
    main()
