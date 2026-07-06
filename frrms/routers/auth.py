from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..dependencies import get_current_user


templates = Jinja2Templates(directory="frrms/templates")

router = APIRouter(include_in_schema=False)


# In a real system this would be replaced by a proper users store
# with salted + hashed passwords.
DUMMY_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"username": "admin", "password": "admin123", "role": "admin"},
    "coordinator": {
        "username": "coordinator",
        "password": "coordinator123",
        "role": "coordinator",
    },
    "field": {"username": "field", "password": "field123", "role": "field_personnel"},
    "field_personnel": {
        "username": "field_personnel",
        "password": "field123",
        "role": "field_personnel",
    },
    "field personnel": {
        "username": "field personnel",
        "password": "field123",
        "role": "field_personnel",
    },
    "viewer": {"username": "viewer", "password": "viewer123", "role": "viewer"},
}


@router.get("/login", response_class=HTMLResponse, name="login")
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "page": "login",
            "error": None,
        },
    )


@router.post("/login", response_class=HTMLResponse, response_model=None)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> RedirectResponse | HTMLResponse:
    user = DUMMY_USERS.get(username)
    if not user or user["password"] != password:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "page": "login",
                "error": "Invalid username or password.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    request.session["user"] = {"username": user["username"], "role": user["role"]}

    if user["role"] == "volunteer_pending":
        return RedirectResponse(url="/team-onboarding", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/logout", name="logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


@router.get("/me", response_class=HTMLResponse, name="me")
async def me(
    request: Request,
    user=Depends(get_current_user),
) -> HTMLResponse:
    """
    Simple endpoint to inspect the current session user.
    """
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page": "dashboard",
            "total_rescued": 0,
            "active_teams": 0,
            "total_shelters": 0,
            "inventory_percentage": 0,
            "district_names": [],
            "victim_counts": [],
        },
    )


