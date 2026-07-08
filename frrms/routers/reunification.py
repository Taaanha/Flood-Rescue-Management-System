from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import require_role
from ..ml.matching import PersonRecord, compute_matches

templates = Jinja2Templates(directory="frrms/templates")
router = APIRouter()

FOUND_STATUSES = ("rescued", "in_shelter", "hospitalized")


def _ensure_matching_column(db: Session) -> None:
    db.execute(text("ALTER TABLE victims ADD COLUMN IF NOT EXISTS matched_victim_id INTEGER"))
    db.execute(text("ALTER TABLE persons ADD COLUMN IF NOT EXISTS age_min INTEGER"))
    db.execute(text("ALTER TABLE persons ADD COLUMN IF NOT EXISTS age_max INTEGER"))

def _load_by_status(db: Session, statuses: tuple[str, ...]) -> list[PersonRecord]:
    placeholders = ", ".join(f"'{s}'" for s in statuses)
    rows = db.execute(
        text(
            f"""
            SELECT v.victim_id AS id, p.full_name, l.district, p.gender, p.age_min, p.age_max, v.status
            FROM victims v
            JOIN persons p ON p.person_id = v.person_id
            LEFT JOIN locations l ON l.location_id = p.location_id
            WHERE v.status IN ({placeholders})
              AND (v.matched_victim_id IS NULL)
            ORDER BY v.victim_id DESC
            LIMIT 500
            """
        )
    ).mappings().all()
    return [
        PersonRecord(r["id"], r["full_name"], r["district"], r["gender"], r["age_min"], r["age_max"], r["status"])
        for r in rows
    ]


@router.get("/admin/missing-matches", response_class=HTMLResponse, name="missing_matches")
async def missing_matches_page(
    request: Request,
    user: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    _ensure_matching_column(db)
    db.commit()

    missing = _load_by_status(db, ("missing",))
    found = _load_by_status(db, FOUND_STATUSES)
    matches = compute_matches(missing, found) if missing and found else {}

    # Build a simple ordered list for the template: only missing persons
    # that have at least one qualifying candidate.
    rows = []
    for m in missing:
        candidates = matches.get(m.victim_id, [])
        if candidates:
            rows.append({"missing": m, "candidates": candidates})

    return templates.TemplateResponse(
        "missing_matches.html",
        {
            "request": request,
            "page": "missing_matches",
            "role": user.get("role", ""),
            "rows": rows,
            "missing_count": len(missing),
            "found_count": len(found),
            "message": request.query_params.get("msg", ""),
        },
    )


@router.post("/admin/missing-matches/confirm", response_model=None)
async def confirm_match(
    missing_victim_id: int = Form(...),
    found_victim_id: int = Form(...),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    _ensure_matching_column(db)
    db.execute(
        text(
            """
            UPDATE victims
            SET status = 'reunited', matched_victim_id = :found_id
            WHERE victim_id = :missing_id
            """
        ),
        {"found_id": found_victim_id, "missing_id": missing_victim_id},
    )
    db.commit()
    return RedirectResponse(url="/admin/missing-matches?msg=Match+confirmed+-+marked+as+reunited", status_code=303)


@router.post("/admin/missing-matches/dismiss", response_model=None)
async def dismiss_candidate(
    missing_victim_id: int = Form(...),
    found_victim_id: int = Form(...),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    # No persistence needed for a dismiss -- it just re-renders the page.
    # (Kept as a distinct endpoint in case you later want to log dismissals
    # to suppress the same suggestion in future runs.)
    return RedirectResponse(url="/admin/missing-matches?msg=Suggestion+dismissed", status_code=303)
