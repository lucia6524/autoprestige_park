"""Pré-traduction des descriptions du catalogue (phase 3 SEO).

Traduit UNE FOIS les descriptions FR vers les colonnes description_<lang>
(voir docs/plan-seo-multilingue.md). Idempotent et reprenable : seuls les
véhicules dont la colonne est vide sont traités. La traduction passe par la
fonction interne de l'API (mêmes lots/backoff Google) EN IN-PROCESS — pas
d'appel HTTP à soi-même, donc pas de rate-limit interne, et le quota de
volume par IP ne s'applique pas (usage légitime côté opérateur).

Usage :
    cd backend
    # base locale par défaut (DATABASE_URL de l'environnement / .env)
    python pretranslate_vehicles.py --lang en,de --dry-run
    python pretranslate_vehicles.py --lang en,de

    # base de production Render (URL externe fournie par le dashboard)
    DATABASE_URL="postgresql://user:pass@host/db" python pretranslate_vehicles.py --lang en,de

Sécurité : description FR inchangée ; échec = colonne laissée vide (repli FR
côté API) et simple re-exécution pour reprendre.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("ENVIRONMENT", "development")

CHUNK_SIZE = 8          # véhicules par lot (les descriptions font ~300-600 car)
DELAY_BETWEEN_CHUNKS = 1.0  # politesse envers l'endpoint public de Google


async def run(langs: list[str], dry_run: bool, limit: int | None) -> int:
    from sqlalchemy import select

    from app.database import init_db
    from app.models.commerce import Vehicle
    from app.services.translation import _translate_texts

    await init_db()

    # Import tardif : engine créé APRÈS que l'environnement est finalisé.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_done = 0
    total_failed = 0

    try:
        for lang in langs:
            async with Session() as db:
                result = await db.execute(
                    select(Vehicle).where(
                        Vehicle.is_active.is_(True),
                        Vehicle.description != "",
                        getattr(Vehicle, f"description_{lang}") == "",
                    )
                )
                targets = list(result.scalars().all())
                if limit:
                    targets = targets[:limit]

                print(f"\n=== {lang.upper()} : {len(targets)} description(s) à traduire ===")
                if dry_run:
                    for v in targets[:5]:
                        print(f"  [dry-run] #{v.id} {v.brand} {v.model} ({len(v.description)} car)")
                    if len(targets) > 5:
                        print(f"  … et {len(targets) - 5} autres")
                    continue

                done = failed = 0
                for start in range(0, len(targets), CHUNK_SIZE):
                    chunk = targets[start : start + CHUNK_SIZE]
                    texts = [v.description for v in chunk]
                    try:
                        translated = await _translate_texts(texts, lang.upper())
                    except Exception as exc:  # lot en échec : on tente véhicule par véhicule
                        print(f"  ⚠️ lot {start}-{start + len(chunk)} en échec ({exc}) → unitaire")
                        translated = []
                        for v in chunk:
                            try:
                                out = await _translate_texts([v.description], lang.upper())
                            except Exception as exc2:
                                print(f"  ❌ #{v.id} {v.brand} {v.model} : {exc2}")
                                failed += 1
                                continue
                            if out[0] and out[0].strip():
                                setattr(v, f"description_{lang}", out[0])
                                done += 1
                            else:
                                print(f"  ❌ #{v.id} {v.brand} {v.model} : traduction vide")
                                failed += 1
                        await db.commit()
                        continue

                    for v, tr in zip(chunk, translated, strict=False):
                        if tr and tr.strip():
                            setattr(v, f"description_{lang}", tr)
                            done += 1
                        else:
                            print(f"  ❌ #{v.id} {v.brand} {v.model} : traduction vide")
                            failed += 1
                    await db.commit()
                    if start + CHUNK_SIZE < len(targets):
                        await asyncio.sleep(DELAY_BETWEEN_CHUNKS)

                total_done += done
                total_failed += failed
                print(f"  → {lang}: {done} traduite(s), {failed} échec(s)")
    finally:
        await engine.dispose()

    print(f"\nTerminé : {total_done} traduction(s) écrite(s), {total_failed} échec(s).")
    if total_failed:
        print("Relance le script pour reprendre (les colonnes vides seront retentées).")
    return 1 if total_failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Pré-traduit les descriptions véhicules.")
    parser.add_argument(
        "--lang",
        default="en,de,it,es,pt,ro",
        help="Langues cibles, séparées par des virgules (défaut : toutes)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans traduire")
    parser.add_argument("--limit", type=int, default=None, help="Nombre max de véhicules par langue")
    args = parser.parse_args()

    langs = [code.strip().lower() for code in args.lang.split(",") if code.strip()]
    invalid = [code for code in langs if code not in ("en", "de", "it", "es", "pt", "ro")]
    if invalid:
        sys.exit(f"Langues non supportées : {invalid} (supportées : en, de, it, es, pt, ro)")

    sys.exit(asyncio.run(run(langs, args.dry_run, args.limit)))


if __name__ == "__main__":
    main()
