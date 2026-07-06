"""
One-time (idempotent) seed: populates the `locations` table with one
row per district, using the real BMD station coordinates from the
flood dataset. Needed so the risk map / risk-assessment job has
somewhere to plot predictions.

Run once after deploy:
    python -m frrms.ml.seed_locations
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..database import SessionLocal
from ..models import Location
from .station_district_map import STATION_TO_DISTRICT

DATA_PATH = Path(__file__).resolve().parent / "data" / "FloodPrediction.csv"


def seed() -> None:
    df = pd.read_csv(DATA_PATH)
    df["District"] = df["Station_Names"].map(STATION_TO_DISTRICT)
    df = df.dropna(subset=["District"])

    # One representative row (station) per district.
    per_district = df.drop_duplicates(subset=["District"])

    db = SessionLocal()
    created, skipped = 0, 0
    try:
        for _, row in per_district.iterrows():
            exists = (
                db.query(Location)
                .filter(Location.district == row["District"])
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(
                Location(
                    area_name=row["Station_Names"],
                    district=row["District"],
                    division=None,
                    latitude=row["LATITUDE"],
                    longitude=row["LONGITUDE"],
                )
            )
            created += 1
        db.commit()
    finally:
        db.close()

    print(f"Seeded {created} new locations, skipped {skipped} existing.")


if __name__ == "__main__":
    seed()
