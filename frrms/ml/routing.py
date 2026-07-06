"""
Smart Rescue Routing.

Honest scope: your data has district-level location (text district names)
for both victims and rescue units, not precise GPS coordinates. So this
matches victims to the nearest rescue unit using real district centroids
(haversine distance between district capitals/stations), not turn-by-turn
GPS routing. That's the right level of fidelity for the data you have --
faking street-level routing on top of district-level data would be
dishonest precision.

Algorithm:
  1. Sort pending victims by urgency (hospitalized/critical first).
  2. For each victim, assign the nearest active rescue unit that still
     has spare capacity (assets_count - already_assigned).
  3. Greedy, not globally optimal -- documented tradeoff, fine for a
     dispatch *suggestion* a human coordinator confirms.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

DISTRICT_CENTROIDS: dict[str, tuple[float, float]] = {
    "Bagerhat": (22.43, 89.66),
    "Barisal": (22.70, 90.36),
    "Bhola": (22.70, 90.66),
    "Bogura": (24.88, 89.36),
    "Chandpur": (23.26, 90.67),
    "Chattogram": (22.35, 91.8166),
    "Cox's Bazar": (21.46, 91.98),
    "Cumilla": (23.48, 91.19),
    "Dhaka": (23.78, 90.39),
    "Dinajpur": (25.63, 88.66),
    "Faridpur": (23.61, 89.84),
    "Feni": (23.01, 91.37),
    "Jashore": (23.17, 89.22),
    "Khulna": (22.80, 89.58),
    "Madaripur": (23.17, 90.18),
    "Moulvibazar": (24.29, 91.73),
    "Mymensingh": (24.75, 90.41),
    "Noakhali": (22.29, 91.13),
    "Pabna": (24.12, 89.04),
    "Patuakhali": (21.98, 90.22),
    "Rajshahi": (24.35, 88.56),
    "Rangamati": (22.67, 92.20),
    "Rangpur": (25.72, 89.26),
    "Satkhira": (22.68, 89.07),
    "Sylhet": (24.88, 91.93),
    "Tangail": (24.15, 89.55),
}

# Common alternate spellings/legacy names typed into free-text district fields.
DISTRICT_ALIASES = {
    "chittagong": "Chattogram",
    "comilla": "Cumilla",
    "jessore": "Jashore",
    "bogra": "Bogura",
    "coxs bazar": "Cox's Bazar",
    "cox bazar": "Cox's Bazar",
}

URGENCY_ORDER = {
    "hospitalized": 0,
    "deceased": 1,
    "missing": 2,
    "in_shelter": 3,
    "rescued": 4,
    "reunited": 5,
}


def resolve_district(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    if key in DISTRICT_ALIASES:
        return DISTRICT_ALIASES[key]
    for district in DISTRICT_CENTROIDS:
        if district.lower() == key:
            return district
    return None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@dataclass
class Victim:
    id: int
    full_name: str
    district: str | None
    status: str


@dataclass
class RescueUnit:
    id: int
    name: str
    working_district: str | None
    capacity: int  # assets_count, used as a rough capacity proxy
    assigned: int = 0


@dataclass
class Assignment:
    victim_id: int
    victim_name: str
    victim_district: str | None
    unit_id: int | None
    unit_name: str | None
    distance_km: float | None
    reason: str


def compute_assignments(victims: list[Victim], units: list[RescueUnit]) -> list[Assignment]:
    active_units = [u for u in units if u.capacity > u.assigned]

    ordered = sorted(
        victims,
        key=lambda v: URGENCY_ORDER.get(v.status, 9),
    )

    results: list[Assignment] = []
    for victim in ordered:
        v_district = resolve_district(victim.district)
        v_coords = DISTRICT_CENTROIDS.get(v_district) if v_district else None

        candidates = [u for u in active_units if u.capacity > u.assigned]
        if not candidates:
            results.append(
                Assignment(
                    victim.id, victim.full_name, victim.district,
                    None, None, None, "No available rescue units with spare capacity",
                )
            )
            continue

        if v_coords is None:
            # Unknown/unmatched district -- fall back to whichever unit has
            # the most spare capacity rather than guessing a distance.
            best = max(candidates, key=lambda u: u.capacity - u.assigned)
            best.assigned += 1
            results.append(
                Assignment(
                    victim.id, victim.full_name, victim.district,
                    best.id, best.name, None,
                    "District unrecognized -- assigned by available capacity, not distance",
                )
            )
            continue

        scored = []
        for u in candidates:
            u_district = resolve_district(u.working_district)
            u_coords = DISTRICT_CENTROIDS.get(u_district) if u_district else None
            distance = haversine_km(v_coords, u_coords) if u_coords else None
            scored.append((u, distance))

        # Prefer units with a known distance; among those, nearest first.
        known = [s for s in scored if s[1] is not None]
        if known:
            best_unit, best_distance = min(known, key=lambda s: s[1])
            reason = "Nearest available unit by district centroid distance"
        else:
            best_unit, best_distance = max(scored, key=lambda s: s[0].capacity - s[0].assigned)
            reason = "No unit district match -- assigned by available capacity"

        best_unit.assigned += 1
        results.append(
            Assignment(
                victim.id, victim.full_name, victim.district,
                best_unit.id, best_unit.name, best_distance, reason,
            )
        )

    return results
