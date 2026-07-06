from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role
from ..ml.routing import Victim, RescueUnit, compute_assignments

templates = Jinja2Templates(directory="frrms/templates")
router = APIRouter()


def _ensure_assignment_column(db: Session) -> None:
    db.execute(text("ALTER TABLE victims ADD COLUMN IF NOT EXISTS assigned_rescue_team VARCHAR(150)"))


def _load_pending_victims(db: Session) -> list[Victim]:
    rows = db.execute(
        text(
            """
            SELECT v.victim_id AS id, p.full_name, l.district, v.status
            FROM victims v
            JOIN persons p ON p.person_id = v.person_id
            LEFT JOIN locations l ON l.location_id = p.location_id
            WHERE v.status = 'missing'
              AND (v.assigned_rescue_team IS NULL OR v.assigned_rescue_team = '')
            ORDER BY v.victim_id DESC
            LIMIT 200
            """
        )
    ).mappings().all()
    return [Victim(r["id"], r["full_name"], r["district"], r["status"]) for r in rows]


def _load_active_units(db: Session) -> list[RescueUnit]:
    try:
        rows = db.execute(
            text(
                """
                SELECT
                  rt.team_id AS id,
                  rt.team_name AS name,
                  rt.working_district AS working_district,
                  COALESCE(rt.assets_count, 1) AS capacity,
                  COALESCE((
                    SELECT COUNT(*) FROM victims v2
                    WHERE v2.assigned_rescue_team = rt.team_name AND v2.status = 'missing'
                  ), 0) AS already_assigned
                FROM rescue_teams rt
                WHERE COALESCE(rt.status, 'standby') = 'active'
                """
            )
        ).mappings().all()
    except Exception:
        db.rollback()
        try:
            rows = db.execute(
                text(
                    """
                    SELECT
                      rt.id AS id,
                      rt.name AS name,
                      rt.working_district AS working_district,
                      COALESCE(rt.assets_count, 1) AS capacity,
                      COALESCE((
                        SELECT COUNT(*) FROM victims v2
                        WHERE v2.assigned_rescue_team = rt.name AND v2.status = 'missing'
                      ), 0) AS already_assigned
                    FROM rescue_teams rt
                    WHERE COALESCE(rt.status, 'standby') = 'active'
                    """
                )
            ).mappings().all()
        except Exception:
            db.rollback()
            rows = []

    return [
        RescueUnit(r["id"], r["name"], r["working_district"], int(r["capacity"]), assigned=int(r["already_assigned"]))
        for r in rows
    ]


@router.get("/admin/smart-routing", response_class=HTMLResponse, name="smart_routing")
async def smart_routing_page(
    request: Request,
    user: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _ensure_assignment_column(db)
    db.commit()

    victims = _load_pending_victims(db)
    units = _load_active_units(db)
    assignments = compute_assignments(victims, units) if victims else []

    return templates.TemplateResponse(
        "smart_routing.html",
        {
            "request": request,
            "page": "smart_routing",
            "role": user.get("role", ""),
            "assignments": assignments,
            "unit_count": len(units),
            "message": request.query_params.get("msg", ""),
        },
    )


@router.post("/admin/smart-routing/assign", response_model=None)
async def confirm_assignment(
    victim_id: int = Form(...),
    unit_name: str = Form(...),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _ensure_assignment_column(db)
    db.execute(
        text("UPDATE victims SET assigned_rescue_team = :unit_name WHERE victim_id = :victim_id"),
        {"unit_name": unit_name, "victim_id": victim_id},
    )
    db.commit()
    return RedirectResponse(url=f"/admin/smart-routing?msg=Assigned+to+{unit_name.replace(' ', '+')}", status_code=303)
