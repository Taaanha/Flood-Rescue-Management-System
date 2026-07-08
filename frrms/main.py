from __future__ import annotations

import uvicorn
from fastapi import FastAPI, HTTPException as FastAPIHTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .database import check_database_connection, create_db_and_tables
from .dependencies import normalize_role
from .routers import auth, dashboard, victims, rescue_units, inventory, operations, command, risk, dispatch, reunification, volunteer_ai
app = FastAPI(title="FRRMS Command", docs_url=None, redoc_url=None)
# Session-based authentication
app.add_middleware(
    SessionMiddleware,
    secret_key="CHANGE_ME_TO_A_SECURE_RANDOM_VALUE",
    session_cookie="frrms_session",
)

# Static files
app.mount("/static", StaticFiles(directory="frrms/static"), name="static")

# Routers
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(victims.router)
app.include_router(rescue_units.router)
app.include_router(inventory.router)
app.include_router(operations.router)
app.include_router(command.router)
app.include_router(risk.router)
app.include_router(dispatch.router)
app.include_router(reunification.router)
app.include_router(volunteer_ai.router)


def _default_landing_for_role(role: str | None) -> str:
    normalized = normalize_role(role)
    if normalized == "volunteer_pending":
        return "/team-onboarding"
    if normalized in {"admin", "coordinator", "field_personnel", "viewer"}:
        return "/dashboard"
    return "/login"


@app.on_event("startup")
def startup_event() -> None:
    check_database_connection()
    create_db_and_tables()


@app.exception_handler(StarletteHTTPException)
@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Redirect unauthenticated users to the login page for HTML routes,
    while keeping JSON responses for API-style endpoints if you add any later.
    """
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        role = request.session.get("user", {}).get("role")
        destination = _default_landing_for_role(role)
        if destination == "/login":
            request.session.clear()
        return RedirectResponse(url=destination, status_code=status.HTTP_302_FOUND)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/", include_in_schema=False, response_model=None)
async def root(request: Request) -> RedirectResponse:
    user = request.session.get("user")
    if user:
        destination = _default_landing_for_role(user.get("role"))
        if destination == "/login":
            request.session.clear()
        return RedirectResponse(url=destination, status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


def run():
    uvicorn.run("frrms.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()


