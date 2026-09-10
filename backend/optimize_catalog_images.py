"""
Optimisation locale des images du catalogue Autohaus.

Constat : les transformations d'images Supabase sont une fonctionnalité Pro
(non activée sur ce projet). Ce script fait le travail en local, gratuitement :
il télécharge les images du catalogue, génère des copies WebP redimensionnées
dans le dossier `thumbs/`, et écrit `js/vehicles-thumbs.js` — une table
URL -> fichier local que le frontend consulte automatiquement.

Le catalogue a besoin de ~600px de large ; on génère du 1200px (rétina-safe)
en WebP qualité 68 : division du poids par 4 à 6.

Usage :
    cd backend
    pip install Pillow httpx
    python optimize_catalog_images.py            # complet
    python optimize_catalog_images.py --dry-run  # voit ce qui sera fait
    python optimize_catalog_images.py --rebuild  # régénère tout

Ré-exécutable sans risque : les images déjà converties sont sautées
(sauf --rebuild), et la table est réécrite à chaque exécution.
"""
import argparse
import json
import sys
from pathlib import Path

import httpx

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow manquant : pip install Pillow")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "js" / "vehicles-data.js"
THUMBS_DIR = BASE_DIR / "thumbs"
MAP_FILE = BASE_DIR / "js" / "vehicles-thumbs.js"

MAX_WIDTH = 800   # cartes catalogue ≈ 400px affichées (×2 retina)
QUALITY = 62

# Session HTTP partagée : réutilise les connexions vers Supabase.
HEADERS = {"User-Agent": "AutohausImageOptimizer/1.0"}


def load_catalog_urls(primaries_only: bool = True) -> list[str]:
    """Extrait les URLs d'images du catalogue local.

    Par défaut, seules les images PRINCIPALES de chaque véhicule sont
    traitées (cartes catalogue, lignes compte, photo principale de la
    fiche) : c'est là que se concentre le poids réellement chargé par les
    visiteurs. Les galeries complètes (--all) ne sont vues qu'à l'ouverture
    d'une fiche précise — les garder en pleine résolution est acceptable.
    """
    if not DATA_FILE.exists():
        sys.exit(f"Fichier introuvable : {DATA_FILE}")
    content = DATA_FILE.read_text(encoding="utf-8")
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1 or end <= start:
        sys.exit("Impossible de localiser le tableau de véhicules.")
    try:
        vehicles = json.loads(content[start : end + 1])
    except json.JSONDecodeError as e:
        sys.exit(f"JSON invalide dans {DATA_FILE.name} : {e}")

    urls: list[str] = []
    for v in vehicles:
        images = v.get("images")
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except json.JSONDecodeError:
                images = []
        if not isinstance(images, list):
            images = []
        primary = v.get("image") or (images[0] if images else "")
        if isinstance(primary, str) and primary:
            urls.append(primary)
        if not primaries_only:
            # Galerie complète, image principale exclue (déjà ajoutée)
            urls.extend(
                u for u in images[1:]
                if isinstance(u, str) and u and u != primary
            )
    # Déduplication en conservant l'ordre
    return list(dict.fromkeys(urls))


def webp_name(url: str) -> str:
    """Nom de fichier stable et lisible pour une URL d'image."""
    from urllib.parse import urlparse

    stem = Path(urlparse(url).path).stem  # ex: 1787079943472-0-inbound...
    return f"{stem}.webp"


def download(client: httpx.Client, url: str) -> bytes:
    r = client.get(url)
    r.raise_for_status()
    return r.content


def to_webp(data: bytes, dest: Path) -> int:
    """Convertit en WebP redimensionné. Retourne la taille finale en octets."""
    from io import BytesIO

    im = Image.open(BytesIO(data))
    im = im.convert("RGB")  # gère PNG/RGBA/JPEG uniformément
    if im.width > MAX_WIDTH:
        ratio = MAX_WIDTH / im.width
        im = im.resize((MAX_WIDTH, max(1, round(im.height * ratio))), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "WEBP", quality=QUALITY, method=6)
    return dest.stat().st_size


def main() -> None:
    # Consoles Windows (cp1252) : évite un crash sur les émojis de log.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    parser = argparse.ArgumentParser(description="Génère des miniatures WebP locales du catalogue.")
    parser.add_argument("--dry-run", action="store_true", help="Liste les actions sans rien télécharger")
    parser.add_argument("--rebuild", action="store_true", help="Régénère même les images déjà converties")
    parser.add_argument("--all", action="store_true", help="Traite aussi les galeries complètes (≈1700 images, lourd)")
    args = parser.parse_args()

    urls = load_catalog_urls(primaries_only=not args.all)
    print(f"📦 {len(urls)} images uniques trouvées dans {DATA_FILE.name}")

    mapping: dict[str, str] = {}
    if MAP_FILE.exists() and not args.rebuild:
        try:
            raw = MAP_FILE.read_text(encoding="utf-8")
            json_part = raw[raw.find("{") : raw.rfind("}") + 1]
            mapping = json.loads(json_part)
            print(f"🗂️  Table existante : {len(mapping)} entrée(s) conservée(s)")
        except (json.JSONDecodeError, OSError):
            mapping = {}

    todo = [u for u in urls if args.rebuild or webp_name(u) not in {webp_name(k) for k in mapping}]
    if args.dry_run:
        print(f"👀 Dry-run : {len(todo)} image(s) seraient téléchargées et converties.")
        for u in todo[:5]:
            print(f"   - {u}")
        if len(todo) > 5:
            print(f"   … et {len(todo) - 5} autres")
        return

    done = skipped = failed = 0
    before_bytes = after_bytes = 0

    client = httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True)
    try:
        for i, url in enumerate(todo, 1):
            dest = THUMBS_DIR / webp_name(url)
            try:
                data = download(client, url)
                size = to_webp(data, dest)
                if size < len(data):
                    # On ne garde la copie locale que si elle est vraiment plus
                    # légère que l'original (sinon l'URL d'origine reste utilisée).
                    mapping[url] = f"thumbs/{dest.name}"
                    done += 1
                    before_bytes += len(data)
                    after_bytes += size
                    print(f"  ✅ [{i}/{len(todo)}] {dest.name} — {len(data)//1024} Ko → {size//1024} Ko")
                else:
                    dest.unlink(missing_ok=True)
                    skipped += 1
                    print(f"  ⏭️  [{i}/{len(todo)}] déjà plus légère — original conservé")
            except Exception as e:  # noqa: BLE001 — on continue malgré une image en échec
                failed += 1
                print(f"  ❌ [{i}/{len(todo)}] {url} — {e}")
    finally:
        client.close()

    # Images déjà présentes dans la table mais pas retéléchargées : on compte
    # leur poids pour un rapport complet.
    for url, rel in mapping.items():
        p = BASE_DIR / rel
        if p.exists() and url not in todo:
            skipped += 1
            try:
                after_bytes += p.stat().st_size
            except OSError:
                pass

    # Table pour le frontend : objet global simple, chargé avant api.js.
    lines = ",\n".join(f'  "{url}": "{rel}"' for url, rel in sorted(mapping.items()))
    MAP_FILE.write_text(
        "// Généré par backend/optimize_catalog_images.py — NE PAS ÉDITER À LA MAIN.\n"
        "// Table URL originale -> copie WebP locale (thumbs/).\n"
        f"window.VEHICLE_THUMBS = {{\n{lines}\n}};\n",
        encoding="utf-8",
    )

    saved = before_bytes - after_bytes if before_bytes else 0
    print("\n" + "=" * 50)
    print(f"✅ Converties : {done} | déjà présentes : {skipped} | échecs : {failed}")
    if before_bytes:
        print(f"📉 Poids images téléchargées : {before_bytes//1024//1024} Mo → {after_bytes//1024//1024} Mo")
    print(f"📝 Table écrite : {MAP_FILE.relative_to(BASE_DIR)} ({len(mapping)} entrées)")
    print("→ Déployez le dossier thumbs/ avec le site (Render static l'inclura).")


if __name__ == "__main__":
    main()
