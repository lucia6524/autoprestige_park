import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "frontend" / "public" / "js" / "vehicles-data.js"
IDS = {110, 112, 113, 114, 115, 116, 119, 120}

content = DATA_FILE.read_text(encoding="utf-8")
start = content.find("[")
end = content.rfind("]")
vehicles = json.loads(content[start:end + 1])

for vehicle in vehicles:
    if vehicle.get("id") not in IDS:
        continue

    price = int(vehicle["price"])
    description = vehicle.get("description", "")
    import re
    price_pattern = re.compile(r"(?i)(Prix(?: annoncé)?|PRIX)\s*:?\s*[0-9][0-9 .\u00a0\u202f]*(€)")
    formatted = format(price, ",").replace(",", "\u202f")
    if price_pattern.search(description):
        description = price_pattern.sub(lambda match: f"{match.group(1)} : {formatted} €", description)
        if "€" in description:
            description = description.replace("€ €", "€")
    else:
        description = f"Prix annoncé : {formatted} €\n\n{description}"
    vehicle["description"] = description

DATA_FILE.write_text(content[:start] + json.dumps(vehicles, ensure_ascii=False, indent=2) + content[end + 1:], encoding="utf-8")
print(f"Descriptions synchronisées: {len(IDS)}")
