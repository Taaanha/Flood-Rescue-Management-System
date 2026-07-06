from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role


templates = Jinja2Templates(directory="frrms/templates")

router = APIRouter()


def _redirect(url: str, msg: str = "") -> RedirectResponse:
    if msg:
        url = f"{url}?msg={msg.replace(' ', '+')}"
    return RedirectResponse(url=url, status_code=302)


def _ensure_rescue_units_table(db: Session) -> None:
    exists = db.execute(text("SELECT to_regclass('public.rescue_teams') IS NOT NULL")).scalar()
    if not exists:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS rescue_teams (
                    team_id SERIAL PRIMARY KEY,
                    team_name VARCHAR(150) NOT NULL UNIQUE,
                    status VARCHAR(30) DEFAULT 'standby',
                    assets_count INTEGER DEFAULT 0,
                    contact_number VARCHAR(30),
                    working_district VARCHAR(100),
                    working_place VARCHAR(150)
                )
                """
            )
        )
        db.commit()
        return

    # Make table backward-compatible for both schema variants
    db.execute(text("ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS status VARCHAR(30)"))
    db.execute(text("ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS assets_count INTEGER DEFAULT 0"))
    db.execute(text("ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS contact_number VARCHAR(30)"))
    db.execute(text("ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS working_district VARCHAR(100)"))
    db.execute(text("ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS working_place VARCHAR(150)"))
    db.commit()


@router.get("/rescue-units", response_class=HTMLResponse, name="rescue_units")
async def rescue_units_page(
    request: Request,
    _: dict = Depends(
        require_role(["admin", "coordinator", "field_personnel", "viewer"]),
    ),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _ensure_rescue_units_table(db)
    rescue_units = []
    try:
        rescue_units = db.execute(
            text(
                """
                SELECT
                  rt.team_id AS id,
                  rt.team_name AS name,
                  COALESCE(rt.status, 'standby') AS status,
                  COALESCE(rt.assets_count, 0) AS assets_count,
                  COALESCE(rt.contact_number, '-') AS contact,
                  'N/A' AS current_operation,
                  COALESCE(rt.working_place || ', ' || rt.working_district, rt.working_place, rt.working_district, '-') AS assigned_place,
                  'rescue_teams_sql' AS source
                FROM rescue_teams rt
                ORDER BY rt.team_id DESC
                LIMIT 200
                """
            )
        ).mappings().all()
    except Exception as e:
        print("RESCUE UNIT LIST ERROR (attempt 1):", repr(e))
        db.rollback()
        try:
            rescue_units = db.execute(
                text(
                    """
                    SELECT
                      rt.id AS id,
                      rt.name AS name,
                      COALESCE(rt.status, 'standby') AS status,
                      COALESCE(rt.assets_count, 0) AS assets_count,
                      COALESCE(rt.contact_number, '-') AS contact,
                      'N/A' AS current_operation,
                      COALESCE(rt.working_place || ', ' || rt.working_district, rt.working_place, rt.working_district, '-') AS assigned_place,
                      'rescue_teams_model' AS source
                    FROM rescue_teams rt
                    ORDER BY rt.id DESC
                    LIMIT 200
                    """
                )
            ).mappings().all()
        except Exception as e2:
            print("RESCUE UNIT LIST ERROR (attempt 2):", repr(e2))
            db.rollback()
            try:
                rescue_units = db.execute(
                    text(
                        """
                        SELECT
                          vt.team_id AS id,
                          vt.team_name AS name,
                          'standby' AS status,
                          COALESCE((SELECT COUNT(*) FROM volunteer_team_members vtm WHERE vtm.team_id = vt.team_id), 0) AS assets_count,
                          '-' AS contact,
                          'N/A' AS current_operation,
                          COALESCE(l.area_name || ', ' || l.district, '-') AS assigned_place,
                          'volunteer_teams' AS source
                        FROM volunteer_teams vt
                        LEFT JOIN locations l ON l.location_id = vt.base_location_id
                        ORDER BY vt.team_id DESC
                        LIMIT 200
                        """
                    )
                ).mappings().all()
            except Exception as e3:
                print("RESCUE UNIT LIST ERROR (attempt 3):", repr(e3))
                db.rollback()
                rescue_units = []

    return templates.TemplateResponse(
        "rescue_units.html",
        {
            "request": request,
            "page": "rescue_units",
            "rescue_units": rescue_units,
            "message": request.query_params.get("msg", ""),
        },
    )


@router.post("/rescue-units/create", response_model=None)
async def create_rescue_unit(
    team_name: str = Form(...),
    status_value: str = Form("standby"),
    assets_count: int = Form(1),
    contact_number: str = Form(""),
    working_district: str = Form(""),
    working_place: str = Form(""),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    status_norm = (status_value or "standby").strip().lower()
    if status_norm not in {"active", "standby", "offline"}:
        status_norm = "standby"
    if assets_count < 0:
        assets_count = 0

    team_name = team_name.strip()
    if not team_name:
        return _redirect("/rescue-units", "Team name is required.")
    _ensure_rescue_units_table(db)

    try:
        db.execute(
            text(
                """
                INSERT INTO rescue_teams(team_name, status, assets_count, contact_number, working_district, working_place)
                VALUES (:team_name, :status, :assets_count, :contact_number, :working_district, :working_place)
                """
            ),
            {
                "team_name": team_name,
                "status": status_norm,
                "assets_count": assets_count,
                "contact_number": contact_number.strip() or None,
                "working_district": working_district.strip() or None,
                "working_place": working_place.strip() or None,
            },
        )
        db.commit()
        return _redirect("/rescue-units", "Rescue unit added.")
    except Exception as e:
        print("RESCUE UNIT CREATE ERROR (attempt 1 - insert team_name):", repr(e))
        db.rollback()

    try:
        result = db.execute(
            text(
                """
                UPDATE rescue_teams
                SET status=:status,
                    assets_count=:assets_count,
                    contact_number=COALESCE(contact_number, :contact_number),
                    working_district=COALESCE(:working_district, working_district),
                    working_place=COALESCE(:working_place, working_place)
                WHERE LOWER(team_name)=LOWER(:team_name)
                """
            ),
            {
                "team_name": team_name,
                "status": status_norm,
                "assets_count": assets_count,
                "contact_number": contact_number.strip() or None,
                "working_district": working_district.strip() or None,
                "working_place": working_place.strip() or None,
            },
        )
        if (result.rowcount or 0) > 0:
            db.commit()
            return _redirect("/rescue-units", "Rescue unit updated.")
        db.rollback()
    except Exception as e:
        print("RESCUE UNIT CREATE ERROR (attempt 2 - update team_name):", repr(e))
        db.rollback()

    try:
        db.execute(
            text(
                """
                INSERT INTO rescue_teams(name, status, assets_count, contact_number, working_district, working_place)
                VALUES (:name, :status, :assets_count, :contact_number, :working_district, :working_place)
                """
            ),
            {
                "name": team_name,
                "status": status_norm,
                "assets_count": assets_count,
                "contact_number": contact_number.strip() or None,
                "working_district": working_district.strip() or None,
                "working_place": working_place.strip() or None,
            },
        )
        db.commit()
        return _redirect("/rescue-units", "Rescue unit added.")
    except Exception as e:
        print("RESCUE UNIT CREATE ERROR (attempt 3 - insert name):", repr(e))
        db.rollback()

    try:
        result = db.execute(
            text(
                """
                UPDATE rescue_teams
                SET status=:status,
                    assets_count=:assets_count,
                    contact_number=COALESCE(contact_number, :contact_number),
                    working_district=COALESCE(:working_district, working_district),
                    working_place=COALESCE(:working_place, working_place)
                WHERE LOWER(name)=LOWER(:name)
                """
            ),
            {
                "name": team_name,
                "status": status_norm,
                "assets_count": assets_count,
                "contact_number": contact_number.strip() or None,
                "working_district": working_district.strip() or None,
                "working_place": working_place.strip() or None,
            },
        )
        if (result.rowcount or 0) > 0:
            db.commit()
            return _redirect("/rescue-units", "Rescue unit updated.")
        db.rollback()
    except Exception as e:
        print("RESCUE UNIT CREATE ERROR (attempt 4 - update name):", repr(e))
        db.rollback()

    try:
        _ensure_rescue_units_table(db)
        db.execute(
            text(
                """
                INSERT INTO rescue_teams(team_name, status, assets_count, contact_number, working_district, working_place)
                VALUES (:team_name, :status, :assets_count, :contact_number, :working_district, :working_place)
                """
            ),
            {
                "team_name": team_name,
                "status": status_norm,
                "assets_count": assets_count,
                "contact_number": contact_number.strip() or None,
                "working_district": working_district.strip() or None,
                "working_place": working_place.strip() or None,
            },
        )
        db.commit()
        return _redirect("/rescue-units", "Rescue unit added.")
    except Exception as e:
        print("RESCUE UNIT CREATE ERROR (attempt 5 - final retry):", repr(e))
        db.rollback()
        return _redirect("/rescue-units", "Could not add rescue unit.")


@router.post("/rescue-units/{unit_id}/status", response_model=None)
async def update_rescue_unit_status(
    unit_id: int,
    source: str = Form(...),
    status_value: str = Form(...),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    status_norm = status_value.strip().lower()
    if status_norm not in {"active", "standby", "offline"}:
        return _redirect("/rescue-units", "Invalid status.")

    if source == "rescue_teams_sql":
        db.execute(text("UPDATE rescue_teams SET status=:status WHERE team_id=:id"), {"status": status_norm, "id": unit_id})
        db.commit()
        return _redirect("/rescue-units", "Status updated.")
    if source == "rescue_teams_model":
        db.execute(text("UPDATE rescue_teams SET status=:status WHERE id=:id"), {"status": status_norm, "id": unit_id})
        db.commit()
        return _redirect("/rescue-units", "Status updated.")
    if source == "volunteer_teams":
        return _redirect("/rescue-units", "This team is read-only here. Add or approve a rescue unit to manage status.")
    return _redirect("/rescue-units", "Status update not supported for this team source.")