from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role
from ..models import District, VolunteerRequest
from ..ml.volunteer_balance import PendingRequest, compute_assignments
from .risk import _get_cached_scores

templates = Jinja2Templates(directory="frrms/templates")
router = APIRouter()


def _district_risk_map(db: Session) -> dict[str, float]:
    scores = _get_cached_scores(db)
    return {
        s["district"]: s["probability"]
        for s in scores
        if s.get("district") and s.get("probability") is not None
    }


def _current_volunteer_counts(db: Session) -> dict[str, int]:
    rows = (
        db.query(District.name, func.count(VolunteerRequest.id))
        .join(VolunteerRequest, VolunteerRequest.assigned_district_id == District.id)
        .filter(VolunteerRequest.status == "assigned")
        .group_by(District.name)
        .all()
    )
    return {name: count for name, count in rows}


@router.get("/admin/volunteer-balance", response_class=HTMLResponse, name="volunteer_balance")
async def volunteer_balance_page(
    request: Request,
    user: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    pending_rows = (
        db.query(VolunteerRequest)
        .filter(VolunteerRequest.status == "pending")
        .order_by(VolunteerRequest.created_at.asc())
        .all()
    )
    pending = [PendingRequest(r.id, r.team_name, r.preferred_district) for r in pending_rows]

    district_risk = _district_risk_map(db)
    current_counts = _current_volunteer_counts(db)
    suggestions = compute_assignments(pending, district_risk, current_counts) if pending else []

    # For the "current distribution" panel -- every district we know about
    # (from risk scoring or existing assignments), sorted by risk desc.
    all_districts = sorted(
        set(district_risk.keys()) | set(current_counts.keys()),
        key=lambda d: district_risk.get(d, 0.0),
        reverse=True,
    )
    distribution = [
        {
            "district": d,
            "risk": district_risk.get(d),
            "volunteers": current_counts.get(d, 0),
        }
        for d in all_districts
    ]

    return templates.TemplateResponse(
        "volunteer_balance.html",
        {
            "request": request,
            "page": "volunteer_balance",
            "role": user.get("role", ""),
            "suggestions": suggestions,
            "distribution": distribution,
            "message": request.query_params.get("msg", ""),
        },
    )


@router.post("/admin/volunteer-balance/assign", response_model=None)
async def confirm_volunteer_assignment(
    request_id: int = Form(...),
    district_name: str = Form(...),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    volunteer_request = db.get(VolunteerRequest, request_id)
    if not volunteer_request:
        return RedirectResponse(url="/admin/volunteer-balance?msg=Request+not+found", status_code=303)

    district = db.query(District).filter(District.name == district_name).first()
    if not district:
        district = District(name=district_name)
        db.add(district)
        db.flush()

    volunteer_request.assigned_district_id = district.id
    volunteer_request.assigned_place = volunteer_request.assigned_place or district_name
    volunteer_request.status = "assigned"
    volunteer_request.admin_note = (
        (volunteer_request.admin_note or "") + f" [AI-balanced assignment to {district_name}]"
    ).strip()
    db.add(volunteer_request)
    db.commit()

    return RedirectResponse(
        url=f"/admin/volunteer-balance?msg=Assigned+{volunteer_request.team_name.replace(' ', '+')}+to+{district_name.replace(' ', '+')}",
        status_code=303,
    )
