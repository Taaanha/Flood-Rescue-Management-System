"""
One-time demo seeding: adds standard relief resources (food, water,
medical kits, tarpaulins) to every seeded district's inventory, with
quantities that vary so some districts show low-stock warnings and
others look well-stocked -- a more convincing inventory-health demo
than every row being identical.

Run once:
    python -m frrms.ml.seed_inventory
"""
from __future__ import annotations

import random

from sqlalchemy import text

from ..database import SessionLocal

random.seed(7)

RESOURCES = [
    ("Dry Food Packets", "packet", "Food", (200, 800), 150),
    ("Drinking Water (5L)", "unit", "Water", (300, 1000), 200),
    ("Medical Kits", "kit", "Medical", (10, 60), 15),
    ("Tarpaulin Sheets", "unit", "Shelter Supplies", (50, 300), 40),
]


def _ensure_category(db, name: str) -> int:
    row = db.execute(text("SELECT category_id FROM resource_categories WHERE category_name=:n"), {"n": name}).first()
    if row:
        return row[0]
    row = db.execute(
        text("INSERT INTO resource_categories(category_name) VALUES (:n) RETURNING category_id"),
        {"n": name},
    ).first()
    return row[0]


def _ensure_resource(db, name: str, unit: str, category_id: int) -> int:
    row = db.execute(text("SELECT resource_id FROM resources WHERE resource_name=:n"), {"n": name}).first()
    if row:
        return row[0]
    row = db.execute(
        text(
            """
            INSERT INTO resources(resource_name, unit, category_id, is_consumable)
            VALUES (:name, :unit, :category_id, true)
            RETURNING resource_id
            """
        ),
        {"name": name, "unit": unit, "category_id": category_id},
    ).first()
    return row[0]


def seed() -> None:
    db = SessionLocal()
    created = 0
    try:
        locations = db.execute(text("SELECT location_id, district FROM locations")).fetchall()
        for resource_name, unit, category_name, (lo, hi), threshold in RESOURCES:
            category_id = _ensure_category(db, category_name)
            resource_id = _ensure_resource(db, resource_name, unit, category_id)

            for location_id, district in locations:
                exists = db.execute(
                    text(
                        "SELECT 1 FROM resource_inventory WHERE resource_id=:r AND location_id=:l"
                    ),
                    {"r": resource_id, "l": location_id},
                ).first()
                if exists:
                    continue
                quantity = random.randint(lo, hi)
                db.execute(
                    text(
                        """
                        INSERT INTO resource_inventory(resource_id, location_id, quantity, minimum_threshold)
                        VALUES (:r, :l, :q, :t)
                        """
                    ),
                    {"r": resource_id, "l": location_id, "q": quantity, "t": threshold},
                )
                created += 1
        db.commit()
        print(f"Done. Created {created} inventory rows across {len(locations)} locations.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()