"""Import local du catalogue frontend dans la base SQLite du backend."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "frontend" / "public" / "js" / "vehicles-data.js"
DATABASE_FILE = ROOT / "backend" / "data" / "autoprestige.db"

content = DATA_FILE.read_text(encoding="utf-8")
start = content.find("[")
end = content.rfind("]")
if start < 0 or end <= start:
    raise RuntimeError("Catalogue JSON introuvable dans vehicles-data.js")

vehicles = json.loads(content[start : end + 1])
now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")

with sqlite3.connect(DATABASE_FILE) as connection:
    created = 0
    skipped = 0
    synchronized = 0

    for vehicle in vehicles:
        key = (
            str(vehicle.get("brand", "")).strip(),
            str(vehicle.get("model", "")).strip(),
            int(vehicle.get("year") or 0),
        )
        exists = connection.execute(
            "SELECT 1 FROM vehicles WHERE brand = ? AND model = ? AND year = ? LIMIT 1",
            key,
        ).fetchone()
        if exists:
            connection.execute(
                "UPDATE vehicles SET price = ?, description = ?, updated_at = ? "
                "WHERE brand = ? AND model = ? AND year = ?",
                (
                    float(vehicle.get("price") or 0),
                    str(vehicle.get("description", "")),
                    now,
                    key[0],
                    key[1],
                    key[2],
                ),
            )
            synchronized += 1
            skipped += 1
            continue

        images = vehicle.get("images") or []
        if isinstance(images, str):
            try:
                images = json.loads(images)
            except json.JSONDecodeError:
                images = []
        image = str(vehicle.get("image") or (images[0] if images else ""))

        connection.execute(
            """
            INSERT INTO vehicles (
                category, brand, model, year, fuel, transmission, mileage,
                price, monthly, type, body_category, power, featured, promo,
                is_active, image, images, description, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "voiture",
                str(vehicle.get("brand", "")),
                str(vehicle.get("model", "")),
                int(vehicle.get("year") or 0),
                str(vehicle.get("fuel", "")),
                str(vehicle.get("transmission", "")),
                int(vehicle.get("mileage") or 0),
                float(vehicle.get("price") or 0),
                float(vehicle.get("monthly") or 0),
                "neuf" if vehicle.get("type") == "neuf" else "occasion",
                str(vehicle.get("category", "")),
                int(vehicle.get("power") or 0),
                bool(vehicle.get("featured")),
                bool(vehicle.get("promo")),
                True,
                image,
                json.dumps(images, ensure_ascii=False),
                str(vehicle.get("description", "")),
                now,
                now,
            ),
        )
        created += 1

print(
    f"Import termine: {created} crees, {synchronized} synchronises, "
    f"{skipped} deja presents"
)
