"""
One-time demo data seeding, informed by CURRENT live flood risk.

For every district, this scores real-time flood risk with the trained
model (same one the risk map uses) and seeds shelters + rescue teams
proportional to that risk: districts currently flagged critical/high get
more shelter capacity and more active rescue teams than districts
currently low-risk. This is a setup convenience script (run once before a
demo), not a live feature -- it does not re-run automatically, and it's
worth being explicit about that distinction in your report so it doesn't
get confused with the live /admin/risk-assessment/run feature.

Idempotent-ish: skips creating a shelter/team if one with the same
generated name already exists for that district, so it's safe to re-run
if it fails partway through.

Run:
    python -m frrms.ml.seed_demo_data
"""
from __future__ import annotations

import random

from sqlalchemy import text

from ..database import SessionLocal
from .predict import predict_risk
from .weather import fetch_current_features
from .routing import DISTRICT_CENTROIDS

random.seed(42)  # reproducible demo data


def _get_or_create_location(db, district: str, lat: float, lng: float) -> int:
    row = db.execute(
        text("SELECT location_id FROM locations WHERE district = :d LIMIT 1"),
        {"d": district},
    ).first()
    if row:
        return row[0]
    row = db.execute(
        text(
            """
            INSERT INTO locations (area_name, district, latitude, longitude)
            VALUES (:area, :district, :lat, :lng)
            RETURNING location_id
            """
        ),
        {"area": district, "district": district, "lat": lat, "lng": lng},
    ).first()
    return row[0]


def _shelter_exists(db, name: str) -> bool:
    row = db.execute(text("SELECT 1 FROM shelters WHERE shelter_name = :n LIMIT 1"), {"n": name}).first()
    return row is not None


def _create_shelter(db, name: str, location_id: int, capacity: int, has_medical: bool) -> None:
    db.execute(
        text(
            """
            INSERT INTO shelters (shelter_name, location_id, capacity, current_occupancy, status, has_medical_unit, opened_at)
            VALUES (:name, :location_id, :capacity, :occupancy, CAST('open' AS shelter_status), :has_medical, NOW())
            """
        ),
        {
            "name": name,
            "location_id": location_id,
            "capacity": capacity,
            "occupancy": random.randint(0, int(capacity * 0.4)),
            "has_medical": has_medical,
        },
    )


def _team_exists(db, name: str) -> bool:
    try:
        row = db.execute(text("SELECT 1 FROM rescue_teams WHERE team_name = :n LIMIT 1"), {"n": name}).first()
        if row:
            return True
    except Exception:
        db.rollback()
    try:
        row = db.execute(text("SELECT 1 FROM rescue_teams WHERE name = :n LIMIT 1"), {"n": name}).first()
        return row is not None
    except Exception:
        db.rollback()
        return False


def _create_team(db, name: str, status: str, assets: int, district: str) -> None:
    try:
        db.execute(
            text(
                """
                INSERT INTO rescue_teams (team_name, status, assets_count, contact_number, working_district, working_place)
                VALUES (:name, :status, :assets, :contact, :district, :district)
                """
            ),
            {"name": name, "status": status, "assets": assets, "contact": "01700000000", "district": district},
        )
        return
    except Exception:
        db.rollback()
    db.execute(
        text(
            """
            INSERT INTO rescue_teams (name, status, assets_count, contact_number, working_district, working_place)
            VALUES (:name, :status, :assets, :contact, :district, :district)
            """
        ),
        {"name": name, "status": status, "assets": assets, "contact": "01700000000", "district": district},
    )


def seed() -> None:
    db = SessionLocal()
    created_shelters, created_teams, scored = 0, 0, 0

    try:
        for district, (lat, lng) in DISTRICT_CENTROIDS.items():
            try:
                features = fetch_current_features(lat, lng)
                prediction = predict_risk(features)
                severity = prediction["severity"]
            except Exception as exc:
                print(f"  [warn] {district}: weather/risk fetch failed ({exc}); assuming moderate")
                severity = "moderate"
            scored += 1

            location_id = _get_or_create_location(db, district, lat, lng)

            # Shelter count/capacity scales with current risk.
            shelter_plan = {
                "critical": (3, (300, 600)),
                "high": (2, (200, 400)),
                "moderate": (1, (150, 300)),
                "low": (1, (80, 150)),
            }[severity]
            n_shelters, (cap_lo, cap_hi) = shelter_plan
            for i in range(n_shelters):
                name = f"{district} Relief Camp {i + 1}"
                if _shelter_exists(db, name):
                    continue
                capacity = random.randint(cap_lo, cap_hi)
                has_medical = (i == 0 and severity in ("critical", "high"))
                _create_shelter(db, name, location_id, capacity, has_medical)
                created_shelters += 1

            # Rescue team count/status scales with current risk.
            team_plan = {
                "critical": (2, "active"),
                "high": (2, "active"),
                "moderate": (1, "active"),
                "low": (1, "standby"),
            }[severity]
            n_teams, status = team_plan
            for i in range(n_teams):
                name = f"{district} Rescue Unit {i + 1}"
                if _team_exists(db, name):
                    continue
                _create_team(db, name, status, random.randint(2, 6), district)
                created_teams += 1

            db.commit()
            print(f"  {district:15s} severity={severity:9s} -> {n_shelters} shelter(s), {n_teams} team(s)")

    finally:
        db.close()

    print(f"\nDone. Scored {scored} districts, created {created_shelters} shelters and {created_teams} rescue teams.")


if __name__ == "__main__":
    seed()
