from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role
from ..models import Alert, Location
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
        .all()
    )
    results = []
    for loc in locations:
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


SEVERITY_TO_ALERT = {"critical", "high"}


@router.post("/admin/risk-assessment/run", response_model=None)
async def run_risk_assessment(
    user: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> dict:
    """
    Scores every seeded district location against the flood-risk model
    and auto-creates an Alert for any district at high/critical risk,
    reusing the same Alert table the dashboard map already renders.
    """
    scores = _score_all_locations(db)
    _CACHE["results"] = scores
    _CACHE["computed_at"] = time.time()

    created = []
    for entry in scores:
        if entry.get("severity") not in SEVERITY_TO_ALERT:
            continue

        recent = (
            db.query(Alert)
            .filter(
                Alert.location_id == entry["location_id"],
                Alert.status == "issued",
                Alert.alert_type == "flood_warning",
            )
            .first()
        )
        if recent:
            continue  # avoid duplicate open alerts for the same district

        alert = Alert(
            location_id=entry["location_id"],
            alert_type="flood_warning",
            severity=entry["severity"],
            message=(
                f"AI flood-risk model flags {entry['district']} at "
                f"{entry['severity'].upper()} risk "
                f"(probability={entry['probability']})."
            ),
            status="issued",
            issued_by=None,
        )
        db.add(alert)
        created.append(entry["district"])

    db.commit()
    return {"scored": len(scores), "alerts_created": created}
