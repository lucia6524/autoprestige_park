"""
Import des véhicules du catalogue local (js/vehicles-data.js) vers l'API admin.

Usage:
    cd backend
    pip install httpx   # déjà dans requirements.txt

    # Via variables d'environnement
    export ADMIN_EMAIL="admin@autoprestige.fr"
    export ADMIN_PASSWORD="votre-mot-de-passe-admin"
    python import_vehicles.py

    # Ou via arguments (l'API par défaut pointe vers la prod)
    python import_vehicles.py --email admin@autoprestige.fr --password "mdp" \
        --api https://autoprestige-api.onrender.com/api

Le script est idempotent : il récupère les véhicules déjà présents et ne crée
que les manquants (détection par marque + modèle + année).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx

# Chemin du fichier de données locales (relatif à ce script)
DATA_FILE = Path(__file__).resolve().parent.parent / "js" / "vehicles-data.js"
API_DEFAULT = "https://autoprestige-api.onrender.com/api"


def load_fallback_vehicles() -> list[dict]:
    """Extrait le tableau JSON de window.FALLBACK_VEHICLES depuis vehicles-data.js."""
    if not DATA_FILE.exists():
        sys.exit(f"Fichier introuvable : {DATA_FILE}")
    content = DATA_FILE.read_text(encoding="utf-8")

    # Récupère le contenu entre le premier '[' et le dernier ']'
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1 or end <= start:
        sys.exit("Impossible de localiser le tableau de véhicules dans le fichier.")
    try:
        vehicles = json.loads(content[start : end + 1])
    except json.JSONDecodeError as e:
        sys.exit(f"JSON invalide dans {DATA_FILE.name} : {e}")
    if not isinstance(vehicles, list) or not vehicles:
        sys.exit("Aucun véhicule trouvé dans le fichier de données locales.")
    return vehicles


def to_api_payload(v: dict) -> dict:
    """
    Convertit un véhicule du format frontend vers le schéma admin (VehicleIn).

    Différence clé de format :
    - Le frontend met la carrosserie dans `category` ("Cabriolet", "Berline", "SUV"...)
    - L'API admin attend `category` = voiture|camping-car|machine-agricole
      et `body_category` = la carrosserie
    - `images` est un tableau côté frontend, une chaîne JSON côté API
    """
    images = v.get("images") or []
    if isinstance(images, str):
        try:
            images = json.loads(images)
        except json.JSONDecodeError:
            images = []
    if not isinstance(images, list):
        images = []

    image = v.get("image") or (images[0] if images else "")

    return {
        "category": "voiture",  # le catalogue local ne contient que des voitures
        "brand": str(v.get("brand", "")).strip(),
        "model": str(v.get("model", "")).strip(),
        "year": int(v.get("year") or 0),
        "fuel": str(v.get("fuel") or ""),
        "transmission": str(v.get("transmission") or ""),
        "mileage": int(v.get("mileage") or 0),
        "price": float(v.get("price") or 0),
        "monthly": float(v.get("monthly") or 0),
        "type": "neuf" if v.get("type") == "neuf" else "occasion",
        "body_category": str(v.get("category") or ""),
        "power": int(v.get("power") or 0),
        "featured": bool(v.get("featured")),
        "promo": bool(v.get("promo")),
        "is_active": True,
        "image": image,
        "images": json.dumps(images, ensure_ascii=False),
        "description": str(v.get("description") or ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Importe le catalogue local vers l'API admin.")
    parser.add_argument("--api", default=os.getenv("API_BASE", API_DEFAULT), help="Base URL de l'API (ex: https://autoprestige-api.onrender.com/api)")
    parser.add_argument("--email", default=os.getenv("ADMIN_EMAIL", ""), help="Email du compte admin")
    parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD", ""), help="Mot de passe admin")
    parser.add_argument("--dry-run", action="store_true", help="Affiche ce qui serait importé sans rien créer")
    args = parser.parse_args()

    if not args.email or not args.password:
        sys.exit("Email et mot de passe admin requis (--email / --password ou ADMIN_EMAIL / ADMIN_PASSWORD).")

    vehicles = load_fallback_vehicles()
    print(f"📦 {len(vehicles)} véhicules chargés depuis {DATA_FILE.name}")

    client = httpx.Client(timeout=30)

    # 1) Login admin
    print("🔑 Connexion admin…")
    r = client.post(
        f"{args.api}/auth/login",
        json={"email": args.email, "password": args.password},
    )
    if r.status_code != 200:
        sys.exit(f"❌ Échec du login ({r.status_code}) : {r.text[:300]}")
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✅ Connecté")

    # 2) Véhicules déjà présents (pour éviter les doublons)
    print("📋 Récupération des véhicules existants…")
    existing = client.get(f"{args.api}/admin/vehicles", headers=headers, params={"limit": 200})
    if existing.status_code == 200:
        existing_list = existing.json()
    else:
        print(f"⚠️ Impossible de lister les véhicules ({existing.status_code}), import complet sans dédup.")
        existing_list = []
    existing_keys = {
        (v.get("brand", "").strip().lower(), v.get("model", "").strip().lower(), int(v.get("year") or 0))
        for v in existing_list
    }

    created = 0
    skipped = 0
    failed = 0

    for i, v in enumerate(vehicles, 1):
        payload = to_api_payload(v)
        key = (payload["brand"].lower(), payload["model"].lower(), payload["year"])
        if key in existing_keys:
            print(f"  ⏭️  [{i}/{len(vehicles)}] {payload['brand']} {payload['model']} ({payload['year']}) — déjà présent, ignoré")
            skipped += 1
            continue

        print(f"  ➕ [{i}/{len(vehicles)}] {payload['brand']} {payload['model']} ({payload['year']})…")
        if args.dry_run:
            created += 1
            continue

        r = client.post(f"{args.api}/admin/vehicles", headers=headers, json=payload)
        if r.status_code in (200, 201):
            created += 1
        else:
            failed += 1
            print(f"     ❌ Erreur {r.status_code} : {r.text[:200]}")

    print("\n" + "=" * 50)
    print(f"Terminé : {created} créé(s), {skipped} ignoré(s), {failed} en échec"
          + (" (dry-run)" if args.dry_run else ""))
    if created and not args.dry_run:
        print("💡 Le catalogue du site se mettra à jour automatiquement "
              "(cache local rafraîchi dans les 30 min, ou après un rechargement).")


if __name__ == "__main__":
    main()