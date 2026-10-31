import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "frontend" / "public" / "js" / "vehicles-data.js"

updates = [
("BMW", 2020, 83900, 29900, "M135i xDrive"),
("BMW", 2018, 31786, 19900, "Série 1 120i"),
("Audi", 2016, 98000, 26900, "RS Q3"),
("BMW", 2020, 113000, 18900, "Série 1 118d M Sport"),
("BMW", 2021, 106100, 37900, "X4 M40d"),
("Audi", 2021, 57700, 54900, "Q8 60 TFSI e quattro"),
("Audi", 2012, 164000, 9900, "A4 2.0 TDI"),
("Peugeot", 2013, 114300, 6900, "208"),
("SEAT", 2023, 42000, 25900, "Ateca FR"),
("SEAT", 2018, 120000, 12900, "Arona"),
("Volvo", 2014, 128054, 11900, "V40 Cross Country"),
("Citroen", 2016, 113959, 8900, "C4 Cactus"),
("Citroen", 2011, 107000, 6500, "C3 HDi 70"),
("Kia", 2015, 95000, 7500, "Picanto"),
("BMW", 2014, 95000, 23900, "X5 xDrive30d"),
("BMW", 2013, 181000, 8900, "Série 1 116d"),
("Skoda", 2018, 92000, 19900, "Superb"),
("Renault", 2019, 101000, 10900, "Clio 1.0"),
("Audi", 2018, 91800, 18900, "A3 Limousine"),
("Jaguar", 2023, 67935, 31900, "XE D200"),
("BMW", 2017, 98000, 22900, "X3 20d xDrive M Sport"),
("Audi", 2014, 126000, 9900, "A1"),
("BMW", 2020, 61464, 25900, "318d Touring"),
("Audi", 2013, 80100, 11900, "A4 Turbo"),
("Honda", 2019, 35541, 39900, "Civic Type R"),
("Opel", 2020, 44131, 12900, "Corsa"),
("Audi", 2014, 91000, 13900, "Q3 35 TFSI"),
("Audi", 2017, 112000, 21900, "A5 2.0 TFSI"),
("Jaguar", 2021, 59800, 25900, "E-PACE"),
("SEAT", 2018, 69553, 19900, "Ateca FR 1.4"),
("Volkswagen", 2020, 131000, 28900, "T6 Transporter"),
("Toyota", 2017, 89050, 22900, "RAV4 2.5 Active"),
("Audi", 2022, 17629, 28900, "A3 40 TFSI e"),
("Volkswagen", 2023, 50000, 39900, "Amarok"),
("Audi", 2022, 14000, 39900, "A6 Avant 40 TDI"),
("Land Rover", 2022, 65000, 34900, "Range Rover Evoque P300e"),
("Skoda", 2020, 54000, 27900, "Kodiaq"),
("BMW", 2015, 33000, 16900, "Série 5 530e"),
("Land Rover", 2012, 132600, 12900, "Range Rover Evoque 4x4"),
("Audi", 2015, 92000, 14900, "Q3 2.0 TDI"),
("BMW", 2017, 110000, 21900, "X3 20d xDrive M Sport"),
("Opel", 2018, 82713, 13900, "Grandland X"),
("Audi", 2018, 59000, 23900, "A3 Sportback 2.0"),
("Opel", 2020, 75500, 16900, "grandland X"),
("Volkswagen", 2018, 75000, 18900, "Passat"),
("Citroen", 2012, 170000, 5900, "C3 1.6 HDi"),
("Audi", 2015, 178700, 17900, "A6 Allroad"),
("Mini", 2020, 20100, 39900, "Cooper S John Cooper Works GP"),
("Renault", 2013, 73050, 7900, "Clio dCi"),
("BMW", 2021, 67900, 27900, "320i M Sport"),
("Peugeot", 2022, 8250, 16900, "208 1.2 PureTech"),
("BMW", 2020, 133000, 17900, "Série 1 118d M Sport"),
("Peugeot", 2016, 95000, 10900, "208 GT Line"),
("BMW", 2013, 134000, 12900, "320d Touring"),
("Volkswagen", 2013, 164000, 9900, "Golf 7"),
("Hyundai", 2017, 127000, 14900, "Tucson"),
("Audi", 2020, 110284, 23900, "A4 Avant"),
("Volvo", 2019, 146000, 25900, "XC60 II"),
("BMW", 2009, 212000, 7900, "120 Coupé"),
("Volkswagen", 2016, 110296, 15900, "Polo GTI"),
("Bentley", 2018, 65590, 89900, "Flying Spur S"),
("Kia", 2019, 72935, 26900, "Stinger"),
]

content = DATA_FILE.read_text(encoding="utf-8")
start = content.find("[")
end = content.rfind("]")
vehicles = json.loads(content[start:end + 1])

updated = []
missing = []
ambiguous = []

for brand, year, mileage, price, label in updates:
    candidates = [
        v for v in vehicles
        if v.get("type") == "occasion"
        and str(v.get("brand", "")).lower().startswith(brand.lower())
        and int(v.get("year") or 0) == year
        and int(v.get("mileage") or 0) == mileage
    ]
    if len(candidates) != 1:
        (ambiguous if candidates else missing).append((brand, label, year, mileage, len(candidates)))
        continue

    vehicle = candidates[0]
    old_price = float(vehicle.get("price") or 0)
    vehicle["price"] = price
    description = str(vehicle.get("description", ""))
    import re
    description = re.sub(
        r"(?i)(Prix(?: annoncé)?\s*:?\s*)[0-9][0-9 .\u00a0\u202f]*(€)",
        lambda match: match.group(1) + f"{price:,}".replace(",", "\u202f") + match.group(2),
        description,
    )
    if not re.search(r"(?i)Prix(?: annoncé)?\s*:?", description):
        description = f"Prix annoncé : {price:,}".replace(",", "\u202f") + " €\n\n" + description
    vehicle["description"] = description
    updated.append((brand, vehicle.get("model"), old_price, price))

if missing or ambiguous:
    raise RuntimeError(f"Missing={missing}; Ambiguous={ambiguous}")

array = json.dumps(vehicles, ensure_ascii=False, indent=2)
header_end = content.find("[")
prefix = content[:start]
suffix = content[end + 1:]
DATA_FILE.write_text(prefix + array + suffix, encoding="utf-8")
print(f"Updated={len(updated)}")
for brand, model, old_price, new_price in updated:
    print(f"{brand} | {model} | {old_price:g} -> {new_price:g}")
