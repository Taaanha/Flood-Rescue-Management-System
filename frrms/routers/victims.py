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


def _ensure_location_for_incident(db: Session, district: str) -> int:
    row = db.execute(
        text("SELECT location_id FROM locations WHERE LOWER(district)=LOWER(:district) ORDER BY location_id DESC LIMIT 1"),
        {"district": district.strip() or "Unknown"},
    ).first()
    if row:
        return int(row[0])
    return int(
        db.execute(
            text(
                """
                INSERT INTO locations(area_name, district, created_at)
                VALUES ('Unknown', :district, NOW())
                RETURNING location_id
                """
            ),
            {"district": district.strip() or "Unknown"},
        ).scalar_one()
    )


@router.get("/victims", response_class=HTMLResponse, name="victims")
async def victims_page(
    request: Request,
    user: dict = Depends(
        require_role(["admin", "coordinator", "field_personnel", "viewer"]),
    ),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    incidents = db.execute(
        text(
            """
            SELECT incident_id, title
            FROM incidents
            ORDER BY created_at DESC NULLS LAST, incident_id DESC
            LIMIT 200
            """
        )
    ).mappings().all()

    victims = db.execute(
        text(
            """
            SELECT
              v.victim_id AS id,
              p.full_name,
              COALESCE(l.district, '-') AS district,
              CASE WHEN v.status IN ('deceased', 'hospitalized') THEN 'critical' ELSE 'stable' END AS health_status,
              COALESCE(ro.operation_name, '-') AS rescue_team,
              '-' AS current_facility,
              v.status
            FROM victims v
            JOIN persons p ON p.person_id = v.person_id
            LEFT JOIN rescue_operations ro ON ro.operation_id = v.rescued_by_operation_id
            LEFT JOIN locations l ON l.location_id = p.location_id
            ORDER BY v.victim_id DESC
            LIMIT 300
            """
        )
    ).mappings().all()

    return templates.TemplateResponse(
        "victims.html",
        {
            "request": request,
            "page": "victims",
            "victims": victims,
            "incidents": incidents,
            "role": user.get("role", ""),
            "message": request.query_params.get("msg", ""),
        },
    )


@router.post("/victims/register", response_model=None)
async def register_victim(
    full_name: str = Form(...),
    incident_id: str | None = Form(None),#changed from int to str
    incident_title: str = Form(""),
    district: str = Form(""),
    status_value: str = Form("rescued"),
    special_needs: str = Form(""),
    _: dict = Depends(require_role(["admin", "coordinator", "field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not full_name.strip():
        return RedirectResponse(url="/victims?msg=Full+name+is+required", status_code=302)

    allowed = {"missing", "rescued", "in_shelter", "hospitalized", "deceased", "reunited"}
    status_norm = (status_value or "rescued").strip().lower()
    if status_norm not in allowed:
        status_norm = "rescued"

    incident_id = int(incident_id) if incident_id and incident_id.strip().isdigit() else None
    resolved_incident_id = incident_id
    if resolved_incident_id is None and incident_title.strip():
    
        existing_incident = db.execute(
            text("SELECT incident_id FROM incidents WHERE LOWER(title)=LOWER(:title) ORDER BY incident_id DESC LIMIT 1"),
            {"title": incident_title.strip()},
        ).first()
        if existing_incident:
            resolved_incident_id = int(existing_incident[0])
        else:
            loc_id = _ensure_location_for_incident(db, district)
            resolved_incident_id = int(
                db.execute(
                    text(
                        """
                        INSERT INTO incidents(title, location_id, severity, status, created_at)
                        VALUES (:title, :location_id, 'moderate', 'active', NOW())
                        RETURNING incident_id
                        """
                    ),
                    {"title": incident_title.strip(), "location_id": loc_id},
                ).scalar_one()
            )

    person_id = db.execute(
        text("INSERT INTO persons(full_name, created_at) VALUES (:full_name, NOW()) RETURNING person_id"),
        {"full_name": full_name.strip()},
    ).scalar_one()

    db.execute(
        text(
            """
            INSERT INTO victims(person_id, incident_id, status, special_needs, rescued_at)
            VALUES (:person_id, :incident_id, :status, :special_needs, NOW())
            """
        ),
        {
            "person_id": int(person_id),
            "incident_id": resolved_incident_id,
            "status": status_norm,
            "special_needs": special_needs.strip() or None,
        },
    )

    if district.strip():
        location_id = db.execute(
            text(
                """
                INSERT INTO locations(area_name, district, created_at)
                VALUES (:area_name, :district, NOW())
                RETURNING location_id
                """
            ),
            {"area_name": "Unknown", "district": district.strip()},
        ).scalar_one()
        db.execute(
            text("UPDATE persons SET location_id=:location_id WHERE person_id=:person_id"),
            {"location_id": int(location_id), "person_id": int(person_id)},
        )

    db.commit()
    return RedirectResponse(url="/victims?msg=Victim+registered", status_code=302)


@router.post("/victims/{victim_id}/leave-shelter", response_model=None)
async def leave_shelter(
    victim_id: int,
    status_value: str = Form("reunited"),
    _: dict = Depends(require_role(["admin", "coordinator", "field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    allowed = {"rescued", "hospitalized", "reunited"}
    status_norm = status_value.strip().lower() or "reunited"
    if status_norm not in allowed:
        status_norm = "reunited"

    db.execute(
        text("UPDATE victims SET status = :status WHERE victim_id = :victim_id"),
        {"status": status_norm, "victim_id": victim_id},
    )
    db.commit()
    return RedirectResponse(url="/victims?msg=Victim+updated+as+left+shelter", status_code=302)

