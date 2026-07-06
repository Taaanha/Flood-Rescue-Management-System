from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus

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
        url = f"{url}?msg={quote_plus(msg)}"
    return RedirectResponse(url=url, status_code=302)


def _ensure_system_user_id(db: Session, username: str, role_name: str) -> int:
    existing = db.execute(text("SELECT user_id FROM users WHERE username=:u"), {"u": username}).first()
    if existing:
        return int(existing[0])

    role = db.execute(text("SELECT role_id FROM roles WHERE role_name=:r"), {"r": role_name}).first()
    if not role:
        role_id = db.execute(
            text("INSERT INTO roles(role_name, description) VALUES (:r, :d) RETURNING role_id"),
            {"r": role_name, "d": f"Auto-created role {role_name}"},
        ).scalar_one()
    else:
        role_id = int(role[0])

    person_id = db.execute(
        text(
            """
            INSERT INTO persons(full_name, created_at)
            VALUES (:name, NOW())
            RETURNING person_id
            """
        ),
        {"name": username},
    ).scalar_one()

    user_id = db.execute(
        text(
            """
            INSERT INTO users(person_id, username, password_hash, role_id, is_active, created_at)
            VALUES (:person_id, :username, :password_hash, :role_id, TRUE, NOW())
            RETURNING user_id
            """
        ),
        {
            "person_id": int(person_id),
            "username": username,
            "password_hash": "dummy",
            "role_id": int(role_id),
        },
    ).scalar_one()
    db.commit()
    return int(user_id)


def _ensure_default_location_id(db: Session) -> int:
    loc = db.execute(text("SELECT location_id FROM locations ORDER BY location_id ASC LIMIT 1")).first()
    if loc:
        return int(loc[0])
    location_id = db.execute(
        text(
            """
            INSERT INTO locations(area_name, district, created_at)
            VALUES ('Unknown', 'Unknown', NOW())
            RETURNING location_id
            """
        )
    ).scalar_one()
    return int(location_id)


def _resolve_incident_id(db: Session, incident_id: int | None, incident_title: str) -> int:
    if incident_id:
        return int(incident_id)
    title = incident_title.strip()
    if title:
        existing = db.execute(
            text("SELECT incident_id FROM incidents WHERE LOWER(title)=LOWER(:title) ORDER BY incident_id DESC LIMIT 1"),
            {"title": title},
        ).first()
        if existing:
            return int(existing[0])
        location_id = _ensure_default_location_id(db)
        created = db.execute(
            text(
                """
                INSERT INTO incidents(title, location_id, severity, status, created_at)
                VALUES (:title, :location_id, 'moderate', 'active', NOW())
                RETURNING incident_id
                """
            ),
            {"title": title, "location_id": location_id},
        ).scalar_one()
        return int(created)
    raise ValueError("Incident is required")


def _resolve_operation_id(db: Session, operation_id: int | None, operation_name: str, incident_id: int) -> int | None:
    if operation_id:
        return int(operation_id)
    name = operation_name.strip()
    if not name:
        return None
    existing = db.execute(
        text(
            """
            SELECT operation_id
            FROM rescue_operations
            WHERE incident_id=:incident_id AND LOWER(operation_name)=LOWER(:name)
            ORDER BY operation_id DESC
            LIMIT 1
            """
        ),
        {"incident_id": incident_id, "name": name},
    ).first()
    if existing:
        return int(existing[0])
    created = db.execute(
        text(
            """
            INSERT INTO rescue_operations(incident_id, operation_name, status, priority, created_at)
            VALUES (:incident_id, :operation_name, 'planned', 3, NOW())
            RETURNING operation_id
            """
        ),
        {"incident_id": incident_id, "operation_name": name},
    ).scalar_one()
    return int(created)


@router.get("/operations", response_class=HTMLResponse, name="operations")
def operations_page(
    request: Request,
    _: dict = Depends(require_role(["admin", "coordinator", "field_personnel", "viewer"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    operations = db.execute(
        text(
            """
            SELECT ro.operation_id, ro.operation_name, ro.status, ro.priority, ro.scheduled_start,
                   i.title AS incident_title, l.area_name, l.district
            FROM rescue_operations ro
            JOIN incidents i ON i.incident_id = ro.incident_id
            LEFT JOIN locations l ON l.location_id = ro.target_location_id
            ORDER BY ro.created_at DESC NULLS LAST, ro.operation_id DESC
            LIMIT 100
            """
        )
    ).mappings().all()
    incidents = db.execute(
        text("SELECT incident_id, title FROM incidents ORDER BY created_at DESC NULLS LAST, incident_id DESC")
    ).mappings().all()
    locations = db.execute(
        text("SELECT location_id, area_name, district FROM locations ORDER BY location_id DESC LIMIT 200")
    ).mappings().all()
    personnel = db.execute(
        text(
            """
            SELECT rp.personnel_id, p.full_name
            FROM rescue_personnel rp
            JOIN persons p ON p.person_id = rp.person_id
            ORDER BY rp.personnel_id DESC
            LIMIT 200
            """
        )
    ).mappings().all()
    return templates.TemplateResponse(
        "operations.html",
        {
            "request": request,
            "page": "operations",
            "operations": operations,
            "incidents": incidents,
            "locations": locations,
            "personnel": personnel,
            "message": request.query_params.get("msg", ""),
        },
    )


@router.post("/operations/create", response_model=None)
def create_operation(
    incident_id: int = Form(...),
    operation_name: str = Form(...),
    description: str = Form(""),
    target_location_id: int | None = Form(None),
    priority: int = Form(3),
    scheduled_start: str = Form(""),
    _: dict = Depends(require_role(["coordinator", "admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not operation_name.strip():
        return _redirect("/operations", "Operation name is required.")
    scheduled = None
    if scheduled_start.strip():
        try:
            scheduled = datetime.fromisoformat(scheduled_start.strip())
        except ValueError:
            scheduled = None
    db.execute(
        text(
            """
            INSERT INTO rescue_operations(
              incident_id, operation_name, description, target_location_id, status, priority, scheduled_start, created_at
            )
            VALUES (:incident_id, :operation_name, :description, :target_location_id, 'planned', :priority, :scheduled_start, NOW())
            """
        ),
        {
            "incident_id": incident_id,
            "operation_name": operation_name.strip(),
            "description": description.strip() or None,
            "target_location_id": target_location_id,
            "priority": priority,
            "scheduled_start": scheduled,
        },
    )
    db.commit()
    return _redirect("/operations", "Operation created.")


@router.post("/incidents/create", response_model=None)
def create_incident(
    title: str = Form(...),
    location_id: int | None = Form(None),
    severity: str = Form("moderate"),
    description: str = Form(""),
    _: dict = Depends(require_role(["coordinator", "admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    title = title.strip()
    if not title:
        return _redirect("/operations", "Incident title is required.")
    allowed = {"low", "moderate", "high", "critical"}
    sev = severity.strip().lower()
    if sev not in allowed:
        sev = "moderate"
    loc_id = location_id or _ensure_default_location_id(db)
    db.execute(
        text(
            """
            INSERT INTO incidents(title, description, location_id, severity, status, created_at)
            VALUES (:title, :description, :location_id, :severity, 'active', NOW())
            """
        ),
        {
            "title": title,
            "description": description.strip() or None,
            "location_id": loc_id,
            "severity": sev,
        },
    )
    db.commit()
    return _redirect("/operations", "Incident added.")


@router.post("/operations/{operation_id}/close", response_model=None)
def close_operation(
    operation_id: int,
    _: dict = Depends(require_role(["coordinator", "admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    db.execute(
        text(
            "UPDATE rescue_operations SET status='completed', completed_at=NOW() WHERE operation_id=:operation_id"
        ),
        {"operation_id": operation_id},
    )
    db.commit()
    return _redirect("/operations", "Operation closed.")


@router.post("/operations/{operation_id}/assign", response_model=None)
def assign_personnel(
    operation_id: int,
    personnel_id: int = Form(...),
    assignment_role: str = Form("general"),
    notes: str = Form(""),
    _: dict = Depends(require_role(["coordinator", "admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    allowed = {"team_lead", "diver", "medic", "boat_operator", "logistics", "general"}
    role = assignment_role.strip().lower()
    if role not in allowed:
        role = "general"
    db.execute(
        text(
            """
            INSERT INTO rescue_assignments(operation_id, personnel_id, assignment_role, assigned_at, notes)
            VALUES (:operation_id, :personnel_id, :assignment_role, NOW(), :notes)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "operation_id": operation_id,
            "personnel_id": personnel_id,
            "assignment_role": role,
            "notes": notes.strip() or None,
        },
    )
    db.commit()
    return _redirect("/operations", "Personnel assigned.")


@router.get("/field-console", response_class=HTMLResponse, name="field_console")
def field_console_page(
    request: Request,
    _: dict = Depends(require_role(["field_personnel"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    incidents = db.execute(text("SELECT incident_id, title FROM incidents ORDER BY incident_id DESC LIMIT 100")).mappings().all()
    operations = db.execute(
        text("SELECT operation_id, operation_name FROM rescue_operations WHERE status IN ('planned','in_progress') ORDER BY operation_id DESC LIMIT 100")
    ).mappings().all()
    resources = db.execute(text("SELECT resource_id, resource_name, unit FROM resources ORDER BY resource_id DESC LIMIT 200")).mappings().all()
    victims = db.execute(
        text(
            """
            SELECT v.victim_id, p.full_name, v.status
            FROM victims v
            JOIN persons p ON p.person_id=v.person_id
            ORDER BY v.victim_id DESC
            LIMIT 100
            """
        )
    ).mappings().all()
    return templates.TemplateResponse(
        "field_console.html",
        {
            "request": request,
            "page": "field_console",
            "incidents": incidents,
            "operations": operations,
            "resources": resources,
            "victims": victims,
            "message": request.query_params.get("msg", ""),
        },
    )


@router.post("/field/victims/rescued", response_model=None)
def add_rescued_victim(
    full_name: str = Form(...),
    incident_id: int | None = Form(None),
    incident_title: str = Form(""),
    operation_id: int | None = Form(None),
    operation_name: str = Form(""),
    phone: str = Form(""),
    special_needs: str = Form(""),
    _: dict = Depends(require_role(["field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        resolved_incident_id = _resolve_incident_id(db, incident_id, incident_title)
    except ValueError:
        return _redirect("/field-console", "Incident id or incident title is required.")
    resolved_operation_id = _resolve_operation_id(db, operation_id, operation_name, resolved_incident_id)

    person_id = db.execute(
        text(
            "INSERT INTO persons(full_name, phone, created_at) VALUES (:full_name, :phone, NOW()) RETURNING person_id"
        ),
        {"full_name": full_name.strip(), "phone": phone.strip() or None},
    ).scalar_one()
    db.execute(
        text(
            """
            INSERT INTO victims(person_id, incident_id, status, special_needs, rescued_by_operation_id, rescued_at)
            VALUES (:person_id, :incident_id, 'rescued', :special_needs, :operation_id, NOW())
            """
        ),
        {
            "person_id": int(person_id),
            "incident_id": resolved_incident_id,
            "special_needs": special_needs.strip() or None,
            "operation_id": resolved_operation_id,
        },
    )
    db.commit()
    return _redirect("/field-console", "Rescued victim added.")


@router.post("/field/victims/{victim_id}/status", response_model=None)
def update_victim_status(
    victim_id: int,
    status_value: str = Form(...),
    _: dict = Depends(require_role(["field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    allowed = {"missing", "rescued", "in_shelter", "hospitalized", "deceased", "reunited"}
    status_norm = status_value.strip().lower()
    if status_norm not in allowed:
        return _redirect("/field-console", "Invalid victim status.")
    db.execute(
        text("UPDATE victims SET status=:status WHERE victim_id=:victim_id"),
        {"status": status_norm, "victim_id": victim_id},
    )
    db.commit()
    return _redirect("/field-console", "Victim status updated.")


@router.post("/field/resource-requests", response_model=None)
def create_resource_request(
    resource_id: int | None = Form(None),
    resource_name: str = Form(""),
    operation_id: int | None = Form(None),
    incident_id: int | None = Form(None),
    incident_title: str = Form(""),
    operation_name: str = Form(""),
    quantity: float = Form(...),
    unit: str = Form(""),
    notes: str = Form(""),
    _: dict = Depends(require_role(["field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if quantity <= 0:
        return _redirect("/field-console", "Quantity must be greater than zero.")
    resolved_resource_id = resource_id
    if not resolved_resource_id:
        name = resource_name.strip()
        if not name:
            return _redirect("/field-console", "Select a resource or type resource name.")
        existing = db.execute(
            text("SELECT resource_id FROM resources WHERE LOWER(resource_name)=LOWER(:name) LIMIT 1"),
            {"name": name},
        ).first()
        if existing:
            resolved_resource_id = int(existing[0])
        else:
            category = db.execute(
                text("SELECT category_id FROM resource_categories WHERE LOWER(category_name)=LOWER('General') LIMIT 1")
            ).first()
            if category:
                category_id = int(category[0])
            else:
                category_id = int(
                    db.execute(
                        text(
                            """
                            INSERT INTO resource_categories(category_name, description)
                            VALUES ('General', 'General resources')
                            RETURNING category_id
                            """
                        )
                    ).scalar_one()
                )
            resolved_resource_id = int(
                db.execute(
                    text(
                        """
                        INSERT INTO resources(resource_name, category_id, unit, description, is_consumable, created_at)
                        VALUES (:resource_name, :category_id, :unit, :description, TRUE, NOW())
                        RETURNING resource_id
                        """
                    ),
                    {
                        "resource_name": name,
                        "category_id": category_id,
                        "unit": unit.strip() or "unit",
                        "description": "Created from field resource request",
                    },
                ).scalar_one()
            )
    resolved_operation_id = operation_id
    if not resolved_operation_id and (incident_id or incident_title.strip() or operation_name.strip()):
        try:
            resolved_incident_id = _resolve_incident_id(db, incident_id, incident_title)
            resolved_operation_id = _resolve_operation_id(db, None, operation_name, resolved_incident_id)
        except ValueError:
            resolved_operation_id = None
    if not resolved_operation_id:
        return _redirect("/field-console", "Operation is required for resource request.")

    db.execute(
        text(
            """
            INSERT INTO resource_allocations(resource_id, operation_id, quantity, unit, status, notes, created_at)
            VALUES (:resource_id, :operation_id, :quantity, :unit, 'requested', :notes, NOW())
            """
        ),
        {
            "resource_id": resolved_resource_id,
            "operation_id": resolved_operation_id,
            "quantity": quantity,
            "unit": unit.strip() or None,
            "notes": notes.strip() or None,
        },
    )
    db.commit()
    return _redirect("/field-console", "Resource request submitted (pending coordinator review).")


@router.post("/field/reports", response_model=None)
def create_field_report(
    request: Request,
    incident_id: int | None = Form(None),
    incident_title: str = Form(""),
    operation_id: int | None = Form(None),
    operation_name: str = Form(""),
    title: str = Form(...),
    content: str = Form(...),
    casualties: int | None = Form(None),
    rescued_count: int | None = Form(None),
    _: dict = Depends(require_role(["field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        resolved_incident_id = _resolve_incident_id(db, incident_id, incident_title)
    except ValueError:
        return _redirect("/field-console", "Incident id or incident title is required.")
    resolved_operation_id = _resolve_operation_id(db, operation_id, operation_name, resolved_incident_id)

    username = request.session.get("user", {}).get("username", "field")
    user_id = _ensure_system_user_id(db, username, "field_personnel")
    db.execute(
        text(
            """
            INSERT INTO incident_reports(
              incident_id, operation_id, report_type, title, content, casualties, rescued_count, submitted_by, submitted_at
            )
            VALUES (:incident_id, :operation_id, 'situation_update', :title, :content, :casualties, :rescued_count, :submitted_by, NOW())
            """
        ),
        {
            "incident_id": resolved_incident_id,
            "operation_id": resolved_operation_id,
            "title": title.strip(),
            "content": content.strip(),
            "casualties": casualties,
            "rescued_count": rescued_count,
            "submitted_by": user_id,
        },
    )
    db.commit()
    return _redirect("/field-console", "Field report submitted.")


@router.get("/coordinator-console", response_class=HTMLResponse, name="coordinator_console")
def coordinator_console_page(
    request: Request,
    _: dict = Depends(require_role(["coordinator", "admin"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    pending_requests = db.execute(
        text(
            """
            SELECT ra.allocation_id, r.resource_name, ra.quantity, ra.unit, ra.status, ra.notes, ro.operation_name
            FROM resource_allocations ra
            JOIN resources r ON r.resource_id = ra.resource_id
            LEFT JOIN rescue_operations ro ON ro.operation_id = ra.operation_id
            WHERE ra.status='requested'
            ORDER BY ra.created_at DESC NULLS LAST, ra.allocation_id DESC
            """
        )
    ).mappings().all()
    reports = db.execute(
        text(
            """
            SELECT ir.report_id, ir.title, ir.report_type, ir.submitted_at, p.full_name AS submitted_by_name, ir.content
            FROM incident_reports ir
            LEFT JOIN users u ON u.user_id = ir.submitted_by
            LEFT JOIN persons p ON p.person_id = u.person_id
            ORDER BY ir.submitted_at DESC NULLS LAST, ir.report_id DESC
            LIMIT 200
            """
        )
    ).mappings().all()
    return templates.TemplateResponse(
        "coordinator_console.html",
        {
            "request": request,
            "page": "coordinator_console",
            "pending_requests": pending_requests,
            "reports": reports,
            "message": request.query_params.get("msg", ""),
        },
    )


@router.post("/resource-requests/{allocation_id}/review", response_model=None)
def review_resource_request(
    request: Request,
    allocation_id: int,
    action: str = Form(...),
    note: str = Form(""),
    _: dict = Depends(require_role(["coordinator", "admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    username = request.session.get("user", {}).get("username", "coordinator")
    role = request.session.get("user", {}).get("role", "coordinator")
    user_id = _ensure_system_user_id(db, username, "admin" if role == "admin" else "coordinator")

    action_norm = action.strip().lower()
    if action_norm == "approve":
        db.execute(
            text(
                """
                UPDATE resource_allocations
                SET status='approved', approved_by=:approved_by,
                    notes = COALESCE(notes, '') || CASE WHEN :note = '' THEN '' ELSE E'\\n[COORDINATOR APPROVED] ' || :note END
                WHERE allocation_id=:allocation_id
                """
            ),
            {"approved_by": user_id, "note": note.strip(), "allocation_id": allocation_id},
        )
        db.commit()
        return _redirect("/coordinator-console", "Resource request approved.")

    db.execute(
        text(
            """
            UPDATE resource_allocations
            SET status='returned', approved_by=:approved_by,
                notes = COALESCE(notes, '') || CASE WHEN :note = '' THEN E'\\n[COORDINATOR REJECTED]' ELSE E'\\n[COORDINATOR REJECTED] ' || :note END
            WHERE allocation_id=:allocation_id
            """
        ),
        {"approved_by": user_id, "note": note.strip(), "allocation_id": allocation_id},
    )
    db.commit()
    return _redirect("/coordinator-console", "Resource request rejected.")


@router.post("/incident-reports/{report_id}/comment", response_model=None)
def comment_on_report(
    request: Request,
    report_id: int,
    comment: str = Form(...),
    _: dict = Depends(require_role(["coordinator", "admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not comment.strip():
        return _redirect("/coordinator-console", "Comment cannot be empty.")
    username = request.session.get("user", {}).get("username", "coordinator")
    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    db.execute(
        text(
            """
            UPDATE incident_reports
            SET content = COALESCE(content, '') || E'\\n\\n[Coordinator Note ' || :stamp || ' by ' || :username || '] ' || :comment
            WHERE report_id=:report_id
            """
        ),
        {"stamp": stamp, "username": username, "comment": comment.strip(), "report_id": report_id},
    )
    db.commit()
    return _redirect("/coordinator-console", "Comment added to report.")
