from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role
from ..models import Location
from ..ml.predict import predict_risk
from ..ml.weather import fetch_current_features

templates = Jinja2Templates(directory="frrms/templates")
router = APIRouter()

# Very small TTL cache so a page full of judges hitting /public/risk-map
# doesn't fire N live weather calls per request.
_CACHE: dict[str, Any] = {"computed_at": 0.0, "results": []}
_CACHE_TTL_SECONDS = 600


def _score_all_locations(db: Session) -> list[dict[str, Any]]:
    locations = (
        db.query(Location)
        .filter(Location.latitude.isnot(None), Location.longitude.isnot(None))
        .order_by(Location.district, Location.id)
        .all()
    )

    # Defensive dedup: keep only the first (lowest id) location per district.
    # Duplicate rows can accumulate from repeated manual test entries (e.g.
    # the "Mark Map Alert" form creating a new location each submission);
    # rather than risk deleting rows with foreign-key dependents under time
    # pressure, just ensure each district is only scored/shown once.
    seen_districts: set[str] = set()
    deduped = []
    for loc in locations:
        key = (loc.district or "").strip().lower()
        if key in seen_districts:
            continue
        seen_districts.add(key)
        deduped.append(loc)

    results = []
    for loc in deduped:
        try:
            features = fetch_current_features(float(loc.latitude), float(loc.longitude))
            prediction = predict_risk(features)
        except Exception as exc:  # live weather call can fail; don't break the page
            prediction = {"probability": None, "severity": "unknown", "error": str(exc)}

        results.append(
            {
                "location_id": loc.id,
                "area_name": loc.area_name,
                "district": loc.district,
                "lat": float(loc.latitude),
                "lng": float(loc.longitude),
                **prediction,
            }
        )
    return results


def _get_cached_scores(db: Session) -> list[dict[str, Any]]:
    now = time.time()
    if now - _CACHE["computed_at"] > _CACHE_TTL_SECONDS or not _CACHE["results"]:
        _CACHE["results"] = _score_all_locations(db)
        _CACHE["computed_at"] = now
    return _CACHE["results"]


@router.get("/public/risk-map", response_class=HTMLResponse, name="public_risk_map")
async def public_risk_map(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """
    Public, unauthenticated page: live AI flood-risk predictions per
    district plotted on a map. This is the judge-facing demo entry point.
    """
    scores = _get_cached_scores(db)
    return templates.TemplateResponse(
        "public_risk_map.html",
        {
            "request": request,
            "scores": scores,
            "cached_at": _CACHE["computed_at"],
        },
    )


@router.post("/admin/risk-assessment/run")
async def run_risk_assessment(
    user: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """
    Scores every seeded district location against the flood-risk model
    and auto-creates an Alert for any district at high/critical risk,
    reusing the same Alert table the dashboard map already renders.
    """
    SEVERITY_TO_ALERT = {"critical", "high"}

    scores = _score_all_locations(db)
    _CACHE["results"] = scores
    _CACHE["computed_at"] = time.time()

    created = []
    errors = 0
    for entry in scores:
        if entry.get("severity") == "unknown":
            errors += 1
            continue
        if entry.get("severity") not in SEVERITY_TO_ALERT:
            continue

        # Raw SQL with explicit enum casts: this database defines
        # alert_type / severity_level / alert_status as native Postgres
        # ENUM types (see flood_management_system.sql), not plain varchar.
        # SQLAlchemy's ORM insert sends bound params typed as VARCHAR by
        # default, which Postgres rejects for enum columns
        # ("column is of type alert_type but expression is of type
        # character varying"). Using CAST(:param AS type) instead of the
        # ":param::type" shorthand -- the shorthand triggers a SQLAlchemy
        # text() tokenizer bug where a bind param immediately followed by
        # "::" fails to be recognized as a parameter at all.
        recent = db.execute(
            text(
                """
                SELECT alert_id FROM alerts
                WHERE location_id = :location_id
                  AND status = CAST('issued' AS alert_status)
                  AND alert_type = CAST(:alert_type AS alert_type)
                LIMIT 1
                """
            ),
            {"location_id": entry["location_id"], "alert_type": "flood_warning"},
        ).first()
        if recent:
            continue  # avoid duplicate open alerts for the same district

        db.execute(
            text(
                """
                INSERT INTO alerts (location_id, alert_type, message, severity, status, issued_by, issued_at)
                VALUES (
                    :location_id,
                    CAST(:alert_type AS alert_type),
                    :message,
                    CAST(:severity AS severity_level),
                    CAST('issued' AS alert_status),
                    NULL,
                    NOW()
                )
                """
            ),
            {
                "location_id": entry["location_id"],
                "alert_type": "flood_warning",
                "message": (
                    f"AI flood-risk model flags {entry['district']} at "
                    f"{entry['severity'].upper()} risk "
                    f"(probability={entry['probability']})."
                ),
                "severity": entry["severity"],
            },
        )
        created.append(entry["district"])

    db.commit()

    if errors and not created:
        msg = f"Risk assessment ran but {errors}/{len(scores)} locations failed (weather fetch error) — check server logs."
    elif created:
        msg = f"Risk assessment complete: {len(created)} new alert(s) created for {', '.join(created)}."
    else:
        msg = f"Risk assessment complete: all {len(scores)} districts scored low/moderate risk, no new alerts needed."

    return RedirectResponse(url=f"/dashboard?msg={msg}", status_code=303)
