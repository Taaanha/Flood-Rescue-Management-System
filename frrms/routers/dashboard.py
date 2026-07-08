from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role
from ..models import Alert, Location, RescueTeam, ResourceInventory, Shelter, VolunteerTeam


templates = Jinja2Templates(directory="frrms/templates")
router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse, name="dashboard")
async def dashboard(
    request: Request,
    user: dict = Depends(require_role(["admin", "coordinator", "field_personnel", "viewer"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    active_teams = db.query(func.count(RescueTeam.id)).scalar() or 0
    total_shelters = db.query(func.count(Shelter.id)).scalar() or 0
    team_pending_approval = db.query(func.count(VolunteerTeam.id)).filter(VolunteerTeam.status == "pending").scalar() or 0

    inventory_rows = db.query(ResourceInventory).all()
    if inventory_rows:
        healthy = sum(1 for row in inventory_rows if (row.quantity or 0) >= (row.threshold or 0))
        inventory_percentage = int((healthy * 100) / len(inventory_rows))
    else:
        inventory_percentage = 0

    # Keep dashboard available even if victims schema is not present.
    total_rescued = 0
    district_names: list[str] = []
    victim_counts: list[int] = []
    try:
        total_rescued = db.execute(
            text("SELECT COUNT(*) FROM victims WHERE LOWER(COALESCE(status::text, '')) = 'rescued'")
        ).scalar() or 0

        victim_distribution = db.execute(
            text(
                """
                SELECT
                    COALESCE(
                        NULLIF(TRIM(s_exact.shelter_name), ''),
                        NULLIF(TRIM(s_district.shelter_name), ''),
                        'Unknown Shelter'
                    ) AS shelter_name,
                    COUNT(*) AS sheltered_count
                FROM victims v
                JOIN persons p ON p.person_id = v.person_id
                LEFT JOIN locations lv ON lv.location_id = p.location_id
                LEFT JOIN shelters s_exact ON s_exact.location_id = p.location_id
                LEFT JOIN LATERAL (
                    SELECT s2.shelter_name
                    FROM shelters s2
                    JOIN locations l2 ON l2.location_id = s2.location_id
                    WHERE lv.district IS NOT NULL
                      AND LOWER(l2.district) = LOWER(lv.district)
                    ORDER BY s2.shelter_id ASC
                    LIMIT 1
                ) AS s_district ON TRUE
                WHERE LOWER(COALESCE(v.status::text, '')) = 'in_shelter'
                GROUP BY 1
                ORDER BY sheltered_count DESC, shelter_name ASC
                LIMIT 10
                """
            )
        ).mappings().all()
        district_names = [row["shelter_name"] for row in victim_distribution]
        victim_counts = [int(row["sheltered_count"]) for row in victim_distribution]
    except SQLAlchemyError:
        db.rollback()

    alerts = (
        db.query(Alert)
        .join(Location, Alert.location_id == Location.id)
        .filter(
            Location.latitude.isnot(None),
            Location.longitude.isnot(None),
            Alert.status == "issued",
        )
        .order_by(Alert.issued_at.desc().nullslast())
        .limit(100)
        .all()
    )
    map_alerts = [
        {
            "id": alert.id,
            "lat": float(alert.location.latitude),  # type: ignore[arg-type]
            "lng": float(alert.location.longitude),  # type: ignore[arg-type]
            "severity": alert.severity or "low",
            "alert_type": alert.alert_type,
            "message": alert.message,
            "area_name": alert.location.area_name if alert.location else "-",
            "district": alert.location.district if alert.location else "-",
            "issued_at": alert.issued_at.isoformat() if alert.issued_at else None,
        }
        for alert in alerts
        if alert.location is not None
    ]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page": "dashboard",
            "total_rescued": total_rescued,
            "active_teams": active_teams,
            "total_shelters": total_shelters,
            "team_pending_approval": team_pending_approval,
            "inventory_percentage": inventory_percentage,
            "district_names": district_names,
            "victim_counts": victim_counts,
            "map_alerts": map_alerts,
            "message": request.query_params.get("msg", ""),
            "role": user.get("role", ""),
        },
    )


@router.post("/dashboard/alerts", response_model=None)
async def create_alert_marker(
    area_name: str = Form(...),
    district_name: str = Form(...),
    division: str = Form(""),
    latitude: float = Form(...),
    longitude: float = Form(...),
    alert_type: str = Form(...),
    severity: str = Form(...),
    message: str = Form(...),
    expires_at: str = Form(""),
    _: dict = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    allowed_types = {"flood_warning", "evacuation_order", "resource_shortage", "all_clear", "general"}
    allowed_severity = {"low", "moderate", "high", "critical"}
    alert_type = alert_type.strip().lower()
    severity = severity.strip().lower()
    if alert_type not in allowed_types:
        return RedirectResponse(url="/dashboard?msg=Invalid+alert+type", status_code=302)
    if severity not in allowed_severity:
        return RedirectResponse(url="/dashboard?msg=Invalid+severity", status_code=302)

    area_name = area_name.strip()
    district_name = district_name.strip()
    if not area_name or not district_name or not message.strip():
        return RedirectResponse(url="/dashboard?msg=Area,+district,+and+message+are+required", status_code=302)

    location = db.query(Location).filter(Location.area_name == area_name, Location.district == district_name).first()
    if not location:
        location = Location(
            area_name=area_name,
            district=district_name,
            division=division.strip() or None,
            latitude=latitude,
            longitude=longitude,
        )
        db.add(location)
        db.flush()
    else:
        location.latitude = latitude
        location.longitude = longitude
        if division.strip():
            location.division = division.strip()
        db.add(location)

    expires_at_dt: Optional[datetime] = None
    if expires_at.strip():
        try:
            expires_at_dt = datetime.fromisoformat(expires_at.strip())
        except ValueError:
            expires_at_dt = None

    db.execute(
        text(
            """
            INSERT INTO alerts (location_id, alert_type, message, severity, status, expires_at, issued_at)
            VALUES (
                :location_id,
                CAST(:alert_type AS alert_type),
                :message,
                CAST(:severity AS severity_level),
                CAST('issued' AS alert_status),
                :expires_at,
                NOW()
            )
            """
        ),
        {
            "location_id": location.id,
            "alert_type": alert_type,
            "message": message.strip(),
            "severity": severity,
            "expires_at": expires_at_dt,
        },
    )
    db.commit()
    return RedirectResponse(url="/dashboard?msg=Alert+marker+added", status_code=302)


@router.post("/dashboard/alerts/{alert_id}/clear", response_model=None)
async def clear_alert_marker(
    alert_id: int,
    _: dict = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    alert = db.get(Alert, alert_id)
    if not alert:
        return RedirectResponse(url="/dashboard?msg=Alert+not+found", status_code=302)
    alert.status = "resolved"
    db.add(alert)
    db.commit()
    return RedirectResponse(url="/dashboard?msg=Alert+marker+removed", status_code=302)

