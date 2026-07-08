from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..dependencies import require_role
from ..models import (
    District,
    Donor,
    InKindDonation,
    Location,
    MonetaryDonation,
    Resource,
    ResourceCategory,
    ResourceDistribution,
    ResourceInventory,
    RescuePersonnel,
    Shelter,
    VolunteerTeam,
    VolunteerTeamApplication,
    VolunteerTeamMember,
    VolunteerRequest,
    Person,
)

templates = Jinja2Templates(directory="frrms/templates")
router = APIRouter()


def _message(request: Request) -> str:
    return request.query_params.get("msg", "")


def _redirect(url: str, message: str) -> RedirectResponse:
    if message:
        url = f"{url}?msg={quote_plus(message)}"
    return RedirectResponse(url=url, status_code=302)


def _invite_code(team_id: int) -> str:
    return f"TEAM-{team_id:04d}"


def _sync_rescue_unit_from_team(
    db: Session,
    team_name: str,
    members_count: int,
    contact_number: str | None = None,
    working_district: str | None = None,
    working_place: str | None = None,
) -> None:
    if not team_name.strip():
        return

    # Keep sync failures isolated so parent approval transaction does not fail.
    with db.begin_nested():
        db.execute(text("ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS working_district VARCHAR(100)"))
        db.execute(text("ALTER TABLE rescue_teams ADD COLUMN IF NOT EXISTS working_place VARCHAR(150)"))

    try:
        with db.begin_nested():
            existing = db.execute(
                text("SELECT team_id FROM rescue_teams WHERE LOWER(team_name)=LOWER(:name) LIMIT 1"),
                {"name": team_name},
            ).first()
            if existing:
                db.execute(
                    text(
                        """
                        UPDATE rescue_teams
                        SET assets_count=:assets_count,
                            status=COALESCE(status, 'standby'),
                            contact_number=COALESCE(contact_number, :contact_number),
                            working_district=COALESCE(:working_district, working_district),
                            working_place=COALESCE(:working_place, working_place)
                        WHERE team_id=:team_id
                        """
                    ),
                    {
                        "assets_count": max(1, members_count),
                        "contact_number": contact_number,
                        "working_district": working_district,
                        "working_place": working_place,
                        "team_id": int(existing[0]),
                    },
                )
                return
            db.execute(
                text(
                    """
                    INSERT INTO rescue_teams(team_name, status, assets_count, contact_number, working_district, working_place)
                    VALUES (:team_name, 'standby', :assets_count, :contact_number, :working_district, :working_place)
                    """
                ),
                {
                    "team_name": team_name,
                    "assets_count": max(1, members_count),
                    "contact_number": contact_number,
                    "working_district": working_district,
                    "working_place": working_place,
                },
            )
            return
    except Exception:
        pass

    try:
        with db.begin_nested():
            existing = db.execute(
                text("SELECT id FROM rescue_teams WHERE LOWER(name)=LOWER(:name) LIMIT 1"),
                {"name": team_name},
            ).first()
            if existing:
                db.execute(
                    text(
                        """
                        UPDATE rescue_teams
                        SET assets_count=:assets_count,
                            status=COALESCE(status, 'standby'),
                            contact_number=COALESCE(contact_number, :contact_number),
                            working_district=COALESCE(:working_district, working_district),
                            working_place=COALESCE(:working_place, working_place)
                        WHERE id=:id
                        """
                    ),
                    {
                        "assets_count": max(1, members_count),
                        "contact_number": contact_number,
                        "working_district": working_district,
                        "working_place": working_place,
                        "id": int(existing[0]),
                    },
                )
                return
            db.execute(
                text(
                    """
                    INSERT INTO rescue_teams(name, status, assets_count, contact_number, working_district, working_place)
                    VALUES (:name, 'standby', :assets_count, :contact_number, :working_district, :working_place)
                    """
                ),
                {
                    "name": team_name,
                    "assets_count": max(1, members_count),
                    "contact_number": contact_number,
                    "working_district": working_district,
                    "working_place": working_place,
                },
            )
            return
    except Exception:
        pass


def _extract_requester_details(admin_note: str | None, fallback: str) -> tuple[str, str]:
    name = fallback
    age = "n/a"
    note = (admin_note or "").strip()
    if not note:
        return name, age
    parts = [p.strip() for p in note.split(";")]
    for part in parts:
        if part.startswith("requester_name="):
            value = part.split("=", 1)[1].strip()
            if value:
                name = value
        if part.startswith("requester_age="):
            value = part.split("=", 1)[1].strip()
            if value:
                age = value
    return name, age


def _ensure_location(
    db: Session,
    area_name: str,
    district_name: str,
    division: str = "",
) -> Location:
    location = (
        db.query(Location)
        .filter(
            Location.area_name == area_name.strip(),
            Location.district == district_name.strip(),
        )
        .first()
    )
    if location:
        return location

    location = Location(
        area_name=area_name.strip(),
        district=district_name.strip(),
        division=division.strip() or None,
    )
    db.add(location)
    db.flush()
    return location


@router.get("/volunteer-registration", response_class=HTMLResponse, name="volunteer_registration")
def volunteer_registration_page(
    request: Request,
    user: dict = Depends(require_role(["viewer"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    username = user.get("username", "")
    requests = (
        db.query(VolunteerRequest)
        .order_by(VolunteerRequest.created_at.desc())
        .filter(VolunteerRequest.team_name == username)
        .all()
    )
    request_rows = []
    for req in requests:
        requester_name, requester_age = _extract_requester_details(req.admin_note, req.team_name)
        request_rows.append(
            {
                "id": req.id,
                "team_name": req.team_name,
                "requester_name": requester_name,
                "requester_age": requester_age,
                "preferred_district": req.preferred_district,
                "preferred_place": req.preferred_place,
                "status": req.status,
                "assigned_district": req.assigned_district,
                "assigned_place": req.assigned_place,
                "admin_note": req.admin_note,
            }
        )
    districts = db.query(District).order_by(District.name.asc()).all()
    return templates.TemplateResponse(
        "volunteer_registration.html",
        {
            "request": request,
            "page": "volunteer_registration",
            "districts": districts,
            "requests": request_rows,
            "message": _message(request),
        },
    )


@router.post("/volunteer-registration", response_model=None)
def submit_volunteer_registration(
    request: Request,
    requester_name: str = Form(""),
    requester_age: int | None = Form(None),
    preferred_district: str = Form(""),
    preferred_place: str = Form(""),
    contact_number: str = Form(""),
    user: dict = Depends(require_role(["viewer"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    username = user.get("username", "")
    requester = requester_name.strip() or username
    age_text = str(requester_age) if requester_age is not None and requester_age > 0 else "n/a"
    volunteer_request = VolunteerRequest(
        team_name=username,
        contact_number=contact_number or None,
        preferred_district=preferred_district or None,
        preferred_place=preferred_place or None,
        admin_note=f"requester_name={requester}; requester_age={age_text}",
        status="pending",
    )
    db.add(volunteer_request)
    db.commit()
    return _redirect("/volunteer-registration", "Volunteer request submitted and waiting for admin assignment.")


@router.get("/admin/assignments", response_class=HTMLResponse, name="admin_assignments")
def admin_assignments_page(
    request: Request,
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    requests = (
        db.query(VolunteerRequest)
        .options(joinedload(VolunteerRequest.assigned_district))
        .order_by(VolunteerRequest.created_at.desc())
        .all()
    )
    request_rows = []
    for req in requests:
        requester_name, requester_age = _extract_requester_details(req.admin_note, req.team_name)
        request_rows.append(
            {
                "id": req.id,
                "requester_name": requester_name,
                "requester_age": requester_age,
                "preferred_district": req.preferred_district,
                "preferred_place": req.preferred_place,
                "status": req.status,
                "assigned_district": req.assigned_district,
                "assigned_place": req.assigned_place,
            }
        )
    districts = db.query(District).order_by(District.name.asc()).all()
    return templates.TemplateResponse(
        "assignments.html",
        {
            "request": request,
            "page": "admin_assignments",
            "requests": request_rows,
            "districts": districts,
            "message": _message(request),
        },
    )

@router.post("/districts", response_model=None)
def create_district(
    name: str = Form(...),
    code: str = Form(""),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    district = db.query(District).filter(District.name == name.strip()).first()
    if district:
        return _redirect("/admin/assignments", "District already exists.")

    db.add(District(name=name.strip(), code=code.strip() or None))
    db.commit()
    return _redirect("/admin/assignments", "District created.")


@router.post("/admin/assignments/{request_id}/assign", response_model=None)
def assign_volunteer_request(
    request_id: int,
    district_id: int = Form(...),
    assigned_place: str = Form(...),
    admin_note: str = Form(""),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    volunteer_request = db.get(VolunteerRequest, request_id)
    if not volunteer_request:
        return _redirect("/admin/assignments", "Volunteer request not found.")

    district = db.get(District, district_id)
    if not district:
        return _redirect("/admin/assignments", "District not found.")

    volunteer_request.assigned_district_id = district_id
    volunteer_request.assigned_place = assigned_place.strip()
    volunteer_request.admin_note = admin_note.strip() or None
    volunteer_request.status = "assigned"
    db.add(volunteer_request)
    db.commit()
    return _redirect("/admin/assignments", "Team assigned successfully.")


@router.post("/admin/volunteer-requests/{request_id}/approve", response_model=None)
def approve_single_volunteer_request(
    request_id: int,
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    volunteer_request = db.get(VolunteerRequest, request_id)
    if not volunteer_request:
        return _redirect("/admin/team-approvals", "Volunteer request not found.")
    volunteer_request.status = "approved"
    db.add(volunteer_request)
    requester_name, _ = _extract_requester_details(volunteer_request.admin_note, volunteer_request.team_name)
    _sync_rescue_unit_from_team(
        db,
        requester_name,
        1,
        volunteer_request.contact_number,
        volunteer_request.preferred_district,
        volunteer_request.preferred_place,
    )
    db.commit()
    return _redirect("/admin/team-approvals", "Volunteer request approved.")


@router.post("/admin/volunteer-requests/{request_id}/reject", response_model=None)
def reject_single_volunteer_request(
    request_id: int,
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    volunteer_request = db.get(VolunteerRequest, request_id)
    if not volunteer_request:
        return _redirect("/admin/team-approvals", "Volunteer request not found.")
    volunteer_request.status = "rejected"
    db.add(volunteer_request)
    db.commit()
    return _redirect("/admin/team-approvals", "Volunteer request rejected.")


@router.get("/shelters", response_class=HTMLResponse, name="shelters")
def shelters_page(
    request: Request,
    _: dict = Depends(require_role(["admin", "coordinator", "field_personnel", "viewer"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    shelters = db.query(Shelter).options(joinedload(Shelter.location)).order_by(Shelter.id.desc()).all()
    return templates.TemplateResponse(
        "shelters.html",
        {
            "request": request,
            "page": "shelters",
            "shelters": shelters,
            "message": _message(request),
        },
    )


@router.post("/shelters", response_model=None)
def create_shelter(
    name: str = Form(...),
    area_name: str = Form(...),
    district_name: str = Form(...),
    division: str = Form(""),
    capacity: int = Form(...),
    has_medical_unit: Optional[str] = Form(None),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if capacity <= 0:
        return _redirect("/shelters", "Capacity must be greater than zero.")

    location = _ensure_location(db, area_name, district_name, division)

    # Raw SQL with an explicit enum cast: shelters.status is a native
    # Postgres ENUM (shelter_status), but the ORM's client-side default
    # ("open") is sent as VARCHAR, which Postgres rejects for enum
    # columns -- same class of bug already found and fixed on alerts.
    db.execute(
        text(
            """
            INSERT INTO shelters (shelter_name, location_id, capacity, current_occupancy, status, has_medical_unit, opened_at)
            VALUES (:name, :location_id, :capacity, 0, CAST('open' AS shelter_status), :has_medical_unit, NOW())
            """
        ),
        {
            "name": name.strip(),
            "location_id": location.id,
            "capacity": capacity,
            "has_medical_unit": bool(has_medical_unit),
        },
    )
    db.commit()
    return _redirect("/shelters", "Shelter added.")


@router.get("/resource-distribution", response_class=HTMLResponse, name="resource_distribution")
def resource_distribution_page(
    request: Request,
    _: dict = Depends(require_role(["admin", "coordinator", "field_personnel", "viewer"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    inventory_items = (
        db.query(ResourceInventory)
        .options(joinedload(ResourceInventory.resource))
        .order_by(ResourceInventory.id.desc())
        .all()
    )
    distributions = (
        db.query(ResourceDistribution)
        .options(joinedload(ResourceDistribution.resource), joinedload(ResourceDistribution.district))
        .order_by(ResourceDistribution.distributed_at.desc())
        .limit(30)
        .all()
    )
    districts = db.query(District).order_by(District.name.asc()).all()
    categories = db.query(ResourceCategory).order_by(ResourceCategory.category_name.asc()).all()
    resources = db.query(Resource).order_by(Resource.name.asc()).all()
    return templates.TemplateResponse(
        "resource_distribution.html",
        {
            "request": request,
            "page": "resource_distribution",
            "inventory_items": inventory_items,
            "distributions": distributions,
            "districts": districts,
            "categories": categories,
            "resources": resources,
            "message": _message(request),
        },
    )


@router.post("/resources", response_model=None)
def create_resource(
    name: str = Form(...),
    unit: str = Form(...),
    category_name: str = Form("General"),
    description: str = Form(""),
    is_consumable: Optional[str] = Form(None),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    name = name.strip()
    unit = unit.strip()
    if not name or not unit:
        return _redirect("/resource-distribution", "Resource name and unit are required.")

    existing = db.query(Resource).filter(Resource.name == name).first()
    if existing:
        return _redirect("/resource-distribution", "Resource already exists.")

    category_name = category_name.strip() or "General"
    category = db.query(ResourceCategory).filter(ResourceCategory.category_name == category_name).first()
    if not category:
        category = ResourceCategory(category_name=category_name)
        db.add(category)
        db.flush()

    resource = Resource(
        name=name,
        unit=unit,
        category_id=category.id,
        description=description.strip() or None,
        is_consumable=bool(is_consumable),
    )
    db.add(resource)
    db.commit()
    return _redirect("/resource-distribution", "Resource created.")


@router.post("/resources/{resource_id}/update", response_model=None)
def update_resource(
    resource_id: int,
    name: str = Form(...),
    unit: str = Form(...),
    category_name: str = Form("General"),
    description: str = Form(""),
    is_consumable: Optional[str] = Form(None),
    _: dict = Depends(require_role(["admin"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    resource = db.get(Resource, resource_id)
    if not resource:
        return _redirect("/resource-distribution", "Resource not found.")

    name = name.strip()
    unit = unit.strip()
    if not name or not unit:
        return _redirect("/resource-distribution", "Resource name and unit are required.")

    existing = db.query(Resource).filter(Resource.name == name, Resource.id != resource_id).first()
    if existing:
        return _redirect("/resource-distribution", "Another resource already has this name.")

    category_name = category_name.strip() or "General"
    category = db.query(ResourceCategory).filter(ResourceCategory.category_name == category_name).first()
    if not category:
        category = ResourceCategory(category_name=category_name)
        db.add(category)
        db.flush()

    resource.name = name
    resource.unit = unit
    resource.category_id = category.id
    resource.description = description.strip() or None
    resource.is_consumable = bool(is_consumable)
    db.add(resource)
    db.commit()
    return _redirect("/resource-distribution", "Resource updated.")


@router.post("/resource-inventory", response_model=None)
def add_or_update_inventory(
    resource_id: int = Form(...),
    area_name: str = Form(...),
    district_name: str = Form(...),
    division: str = Form(""),
    quantity: float = Form(...),
    threshold: float = Form(0),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if quantity < 0:
        return _redirect("/resource-distribution", "Quantity cannot be negative.")
    if threshold < 0:
        return _redirect("/resource-distribution", "Threshold cannot be negative.")

    resource = db.get(Resource, resource_id)
    if not resource:
        return _redirect("/resource-distribution", "Resource not found.")

    location = _ensure_location(db, area_name, district_name, division)

    inventory = (
        db.query(ResourceInventory)
        .filter(
            ResourceInventory.resource_id == resource.id,
            ResourceInventory.location_id == location.id,
        )
        .first()
    )
    if inventory:
        inventory.quantity = (inventory.quantity or 0) + quantity
        inventory.threshold = threshold
        db.add(inventory)
        db.commit()
        return _redirect("/resource-distribution", "Inventory stock added.")

    inventory = ResourceInventory(
        resource_id=resource.id,
        location_id=location.id,
        quantity=quantity,
        threshold=threshold,
    )
    db.add(inventory)
    db.commit()
    return _redirect("/resource-distribution", "Inventory added.")


@router.post("/resource-distribution", response_model=None)
def distribute_resource(
    inventory_id: int = Form(...),
    district_id: Optional[int] = Form(None),
    place: str = Form(""),
    quantity: float = Form(...),
    note: str = Form(""),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    inventory = db.get(ResourceInventory, inventory_id)
    if not inventory:
        return _redirect("/resource-distribution", "Inventory item not found.")
    if quantity <= 0:
        return _redirect("/resource-distribution", "Quantity must be greater than zero.")
    if inventory.quantity < quantity:
        return _redirect("/resource-distribution", "Not enough stock to distribute this amount.")

    inventory.quantity -= quantity
    distribution = ResourceDistribution(
        resource_id=inventory.resource_id,
        district_id=district_id,
        place=place.strip() or None,
        quantity=quantity,
        note=note.strip() or None,
    )
    db.add(distribution)
    db.add(inventory)
    db.commit()
    return _redirect("/resource-distribution", "Resource distributed successfully.")


@router.get("/donations", response_class=HTMLResponse, name="donations")
def donations_page(
    request: Request,
    _: dict = Depends(require_role(["admin", "coordinator", "field_personnel", "viewer"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    monetary = (
        db.query(MonetaryDonation)
        .options(joinedload(MonetaryDonation.donor))
        .order_by(MonetaryDonation.received_at.desc())
        .limit(30)
        .all()
    )
    in_kind = (
        db.query(InKindDonation)
        .options(joinedload(InKindDonation.donor), joinedload(InKindDonation.resource))
        .order_by(InKindDonation.received_at.desc())
        .limit(30)
        .all()
    )
    resources = db.query(Resource).order_by(Resource.name.asc()).all()
    return templates.TemplateResponse(
        "donations.html",
        {
            "request": request,
            "page": "donations",
            "monetary": monetary,
            "in_kind": in_kind,
            "resources": resources,
            "message": _message(request),
        },
    )


@router.post("/donations/monetary", response_model=None)
def add_monetary_donation(
    donor_name: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("BDT"),
    payment_method: str = Form(""),
    transaction_reference: str = Form(""),
    note: str = Form(""),
    _: dict = Depends(require_role(["admin", "coordinator", "viewer"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if amount <= 0:
        return _redirect("/donations", "Donation amount must be greater than zero.")
    donor_name = donor_name.strip()
    if not donor_name:
        return _redirect("/donations", "Donor name is required.")

    donor = db.query(Donor).filter(Donor.donor_name == donor_name).first()
    if not donor:
        donor = Donor(donor_name=donor_name)
        db.add(donor)
        db.flush()

    donation = MonetaryDonation(
        donor_id=donor.id,
        amount=amount,
        currency=currency.strip().upper() or "BDT",
        payment_method=payment_method.strip() or None,
        transaction_reference=transaction_reference.strip() or None,
        note=note.strip() or None,
    )
    db.add(donation)
    db.commit()
    return _redirect("/donations", "Monetary donation added.")


@router.post("/donations/in-kind", response_model=None)
def add_in_kind_donation(
    donor_name: str = Form(...),
    resource_id: int | None = Form(None),
    resource_name: str = Form(""),
    quantity: float = Form(...),
    unit: str = Form(...),
    delivery_method: str = Form(""),
    min_delivery_cost: float | None = Form(None),
    note: str = Form(""),
    _: dict = Depends(require_role(["admin", "coordinator", "viewer"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if quantity <= 0:
        return _redirect("/donations", "Quantity must be greater than zero.")

    donor_name = donor_name.strip()
    if not donor_name:
        return _redirect("/donations", "Donor name is required.")

    donor = db.query(Donor).filter(Donor.donor_name == donor_name).first()
    if not donor:
        donor = Donor(donor_name=donor_name)
        db.add(donor)
        db.flush()

    resource = db.get(Resource, resource_id) if resource_id else None
    if not resource and resource_name.strip():
        category = db.query(ResourceCategory).filter(ResourceCategory.category_name == "Donated Item").first()
        if not category:
            category = ResourceCategory(category_name="Donated Item")
            db.add(category)
            db.flush()
        resource = Resource(
            name=resource_name.strip(),
            unit=unit.strip() or "unit",
            category_id=category.id,
            description="Auto-created from in-kind donation",
            is_consumable=True,
        )
        db.add(resource)
        db.flush()
    if not resource:
        return _redirect("/donations", "Select existing resource or type a new item name.")

    details = []
    if delivery_method.strip():
        details.append(f"Delivery: {delivery_method.strip()}")
    if min_delivery_cost is not None:
        details.append(f"Delivery cost: {min_delivery_cost}")
    merged_note = note.strip()
    if details:
        merged_note = " | ".join(details) if not merged_note else f"{merged_note} | {' | '.join(details)}"

    donation = InKindDonation(
        donor_id=donor.id,
        resource_id=resource.id,
        quantity=quantity,
        unit=unit.strip() or resource.unit,
        note=merged_note or None,
    )
    db.add(donation)
    db.commit()
    return _redirect("/donations", "In-kind donation added.")


@router.get("/team-onboarding", response_class=HTMLResponse, name="team_onboarding")
def team_onboarding_page(
    request: Request,
    user: dict = Depends(require_role(["volunteer_pending", "field_personnel"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    username = user.get("username", "")
    teams = (
        db.query(VolunteerTeam)
        .options(joinedload(VolunteerTeam.base_location))
        .join(VolunteerTeamApplication, VolunteerTeamApplication.team_id == VolunteerTeam.id)
        .filter(
            VolunteerTeamApplication.email == f"{username}@local",
        )
        .order_by(VolunteerTeam.created_at.desc())
        .all()
    )
    created_teams = db.query(VolunteerTeam).order_by(VolunteerTeam.created_at.desc()).limit(20).all()
    all_teams = db.query(VolunteerTeam).order_by(VolunteerTeam.created_at.desc()).all()
    return templates.TemplateResponse(
        "team_onboarding.html",
        {
            "request": request,
            "page": "team_onboarding",
            "teams": teams,
            "created_teams": created_teams,
            "all_teams": all_teams,
            "message": _message(request),
        },
    )


@router.post("/team-onboarding/create-team", response_model=None)
def create_volunteer_team(
    team_name: str = Form(...),
    leader_full_name: str = Form(...),
    leader_email: str = Form(""),
    leader_phone: str = Form(""),
    leader_specialization: str = Form("team_lead"),
    area_name: str = Form(...),
    district_name: str = Form(...),
    division: str = Form(""),
    user: dict = Depends(require_role(["volunteer_pending", "field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    team_name = team_name.strip()
    if not team_name:
        return _redirect("/team-onboarding", "Team name is required.")
    exists = db.query(VolunteerTeam).filter(VolunteerTeam.team_name == team_name).first()
    if exists:
        return _redirect("/team-onboarding", "Team name already exists.")

    location = _ensure_location(db, area_name, district_name, division)
    team = VolunteerTeam(
        team_name=team_name,
        base_location_id=location.id,
        status="pending",
    )
    db.add(team)
    db.flush()

    db.add(
        VolunteerTeamApplication(
            team_id=team.id,
            full_name=leader_full_name.strip(),
            email=(leader_email.strip() or f"{user.get('username', 'leader')}@local"),
            phone=leader_phone.strip() or None,
            specialization=leader_specialization.strip() or "team_lead",
            designation="Team Lead",
            base_location_id=location.id,
            is_leader=True,
            status="pending",
        )
    )
    db.commit()
    return _redirect("/team-onboarding", f"Team created. Share invite code: {_invite_code(team.id)}")


@router.post("/team-onboarding/{team_id}/members", response_model=None)
def add_team_member_application(
    team_id: int,
    full_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    specialization: str = Form("general"),
    designation: str = Form("Volunteer"),
    area_name: str = Form(...),
    district_name: str = Form(...),
    division: str = Form(""),
    _: dict = Depends(require_role(["volunteer_pending", "field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    team = db.get(VolunteerTeam, team_id)
    if not team:
        return _redirect("/team-onboarding", "Team not found.")
    if team.status not in {"pending", "approved"}:
        return _redirect("/team-onboarding", "Team is not accepting members.")

    location = _ensure_location(db, area_name, district_name, division)
    db.add(
        VolunteerTeamApplication(
            team_id=team.id,
            full_name=full_name.strip(),
            email=email.strip() or None,
            phone=phone.strip() or None,
            specialization=specialization.strip() or "general",
            designation=designation.strip() or "Volunteer",
            base_location_id=location.id,
            is_leader=False,
            status="pending",
        )
    )
    db.commit()
    return _redirect("/team-onboarding", "Member application added.")


@router.post("/team-onboarding/join", response_model=None)
def join_team_by_code(
    invite_code: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    specialization: str = Form("general"),
    area_name: str = Form(...),
    district_name: str = Form(...),
    division: str = Form(""),
    _: dict = Depends(require_role(["volunteer_pending", "field_personnel"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    code = invite_code.strip().upper()
    if not code.startswith("TEAM-"):
        return _redirect("/team-onboarding", "Invalid invite code.")
    try:
        team_id = int(code.split("-", 1)[1])
    except ValueError:
        return _redirect("/team-onboarding", "Invalid invite code.")

    team = db.get(VolunteerTeam, team_id)
    if not team:
        return _redirect("/team-onboarding", "Team not found for this invite code.")

    location = _ensure_location(db, area_name, district_name, division)
    db.add(
        VolunteerTeamApplication(
            team_id=team.id,
            full_name=full_name.strip(),
            email=email.strip() or None,
            phone=phone.strip() or None,
            specialization=specialization.strip() or "general",
            designation="Volunteer",
            base_location_id=location.id,
            is_leader=False,
            status="pending",
        )
    )
    db.commit()
    return _redirect("/team-onboarding", "Join request submitted and waiting approval.")


@router.get("/admin/team-approvals", response_class=HTMLResponse, name="team_approvals")
def team_approvals_page(
    request: Request,
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    teams = (
        db.query(VolunteerTeam)
        .options(joinedload(VolunteerTeam.base_location), joinedload(VolunteerTeam.member_applications))
        .order_by(VolunteerTeam.created_at.desc())
        .all()
    )
    all_teams = db.query(VolunteerTeam).order_by(VolunteerTeam.team_name.asc()).all()
    pending_single_requests = (
        db.query(VolunteerRequest)
        .options(joinedload(VolunteerRequest.assigned_district))
        .filter(VolunteerRequest.status == "pending")
        .order_by(VolunteerRequest.created_at.desc())
        .all()
    )
    pending_single_rows = []
    for req in pending_single_requests:
        requester_name, requester_age = _extract_requester_details(req.admin_note, req.team_name)
        pending_single_rows.append(
            {
                "id": req.id,
                "team_name": req.team_name,
                "requester_name": requester_name,
                "requester_age": requester_age,
                "preferred_district": req.preferred_district,
                "preferred_place": req.preferred_place,
                "status": req.status,
            }
        )
    pending_teams = [team for team in teams if any(app.status == "pending" for app in team.member_applications)]
    reviewed_teams = [team for team in teams if team not in pending_teams]
    return templates.TemplateResponse(
        "team_approvals.html",
        {
            "request": request,
            "page": "team_approvals",
            "pending_teams": pending_teams,
            "reviewed_teams": reviewed_teams,
            "pending_single_requests": pending_single_rows,
            "all_teams": all_teams,
            "message": _message(request),
            "invite_code": _invite_code,
        },
    )


def _get_or_create_personnel_from_application(db: Session, app: VolunteerTeamApplication) -> RescuePersonnel:
    person = None
    if app.email:
        person = db.query(Person).filter(Person.email == app.email).first()
    if not person:
        person = Person(
            full_name=app.full_name,
            email=app.email,
            phone=app.phone,
            location_id=app.base_location_id,
        )
        db.add(person)
        db.flush()

    profile = db.query(RescuePersonnel).filter(RescuePersonnel.person_id == person.id).first()
    if profile:
        if app.base_location_id and not profile.base_location_id:
            profile.base_location_id = app.base_location_id
        if app.specialization and not profile.specialization:
            profile.specialization = app.specialization
        profile.status = "available"
        db.add(profile)
        return profile

    profile = RescuePersonnel(
        person_id=person.id,
        designation=app.designation or "Volunteer",
        specialization=app.specialization or "general",
        status="available",
        joined_date=date.today(),
        base_location_id=app.base_location_id,
    )
    db.add(profile)
    db.flush()
    return profile


@router.post("/admin/team-approvals/{team_id}/approve", response_model=None)
def approve_team(
    team_id: int,
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        team = db.get(VolunteerTeam, team_id)
        if not team:
            return _redirect("/admin/team-approvals", "Team not found.")

        pending_apps = (
            db.query(VolunteerTeamApplication)
            .filter(
                VolunteerTeamApplication.team_id == team_id,
                VolunteerTeamApplication.status == "pending",
            )
            .order_by(VolunteerTeamApplication.is_leader.desc(), VolunteerTeamApplication.created_at.asc())
            .all()
        )
        if not pending_apps:
            return _redirect("/admin/team-approvals", "No pending applications for this team.")

        leader_profile = None
        for application in pending_apps:
            personnel = _get_or_create_personnel_from_application(db, application)
            exists = (
                db.query(VolunteerTeamMember)
                .filter(
                    VolunteerTeamMember.team_id == team_id,
                    VolunteerTeamMember.personnel_id == personnel.id,
                )
                .first()
            )
            if not exists:
                db.add(VolunteerTeamMember(team_id=team_id, personnel_id=personnel.id))
            application.status = "approved"
            db.add(application)
            if application.is_leader and leader_profile is None:
                leader_profile = personnel

        if leader_profile:
            team.leader_id = leader_profile.id
        team.status = "approved"
        team.reviewed_at = datetime.utcnow()
        db.add(team)
        working_district = team.base_location.district if team.base_location else None
        working_place = team.base_location.area_name if team.base_location else None
        _sync_rescue_unit_from_team(db, team.team_name, len(pending_apps), None, working_district, working_place)
        db.commit()
        return _redirect("/admin/team-approvals", "Team approved and personnel activated.")
    except Exception:
        db.rollback()
        return _redirect("/admin/team-approvals", "Approval failed due to data issue. Please retry.")


@router.post("/admin/team-approvals/{team_id}/reject", response_model=None)
def reject_team(
    team_id: int,
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    team = db.get(VolunteerTeam, team_id)
    if not team:
        return _redirect("/admin/team-approvals", "Team not found.")

    apps = db.query(VolunteerTeamApplication).filter(VolunteerTeamApplication.team_id == team_id).all()
    for app in apps:
        if app.status == "pending":
            app.status = "rejected"
            db.add(app)
    team.status = "rejected"
    team.reviewed_at = datetime.utcnow()
    db.add(team)
    db.commit()
    return _redirect("/admin/team-approvals", "Team rejected.")


@router.post("/admin/team-approvals/add-single-volunteer", response_model=None)
def add_single_volunteer_to_team(
    team_id: int = Form(...),
    full_name: str = Form(...),
    age: int | None = Form(None),
    phone: str = Form(""),
    specialization: str = Form("general"),
    designation: str = Form("Volunteer"),
    area_name: str = Form("Unknown"),
    district_name: str = Form("Unknown"),
    division: str = Form(""),
    _: dict = Depends(require_role(["admin", "coordinator"])),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        team = db.get(VolunteerTeam, team_id)
        if not team:
            return _redirect("/admin/team-approvals", "Team not found.")
        if not full_name.strip():
            return _redirect("/admin/team-approvals", "Volunteer name is required.")

        location = _ensure_location(db, area_name or "Unknown", district_name or "Unknown", division)
        email_stub = full_name.strip().lower().replace(" ", ".")
        app = VolunteerTeamApplication(
            team_id=team.id,
            full_name=full_name.strip(),
            email=f"{email_stub}@local",
            phone=phone.strip() or None,
            specialization=specialization.strip() or "general",
            designation=designation.strip() or "Volunteer",
            base_location_id=location.id,
            is_leader=False,
            status="approved",
        )
        db.add(app)
        db.flush()

        personnel = _get_or_create_personnel_from_application(db, app)
        exists = (
            db.query(VolunteerTeamMember)
            .filter(
                VolunteerTeamMember.team_id == team.id,
                VolunteerTeamMember.personnel_id == personnel.id,
            )
            .first()
        )
        if not exists:
            db.add(VolunteerTeamMember(team_id=team.id, personnel_id=personnel.id))

        team.status = "approved"
        team.reviewed_at = datetime.utcnow()
        db.add(team)
        member_count = db.query(VolunteerTeamMember).filter(VolunteerTeamMember.team_id == team.id).count()
        _sync_rescue_unit_from_team(
            db,
            team.team_name,
            member_count,
            phone.strip() or None,
            district_name.strip() or None,
            area_name.strip() or None,
        )
        db.commit()
        age_note = f" (age {age})" if age else ""
        return _redirect("/admin/team-approvals", f"Volunteer added to team{age_note} and synced to rescue units.")
    except Exception:
        db.rollback()
        return _redirect("/admin/team-approvals", "Could not add volunteer to team.")