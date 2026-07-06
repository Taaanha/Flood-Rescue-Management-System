from __future__ import annotations

from typing import Callable, Iterable, List, Mapping, Optional

from fastapi import Depends, HTTPException, Request, status


ROLE_ALIASES = {
    "district_manager": "coordinator",
    "team_leader": "volunteer_pending",
}


def normalize_role(role: Optional[str]) -> Optional[str]:
    if role is None:
        return None
    return ROLE_ALIASES.get(role, role)


def get_current_user(request: Request) -> Mapping[str, str]:
    """
    Dependency that returns the current user stored in the session.

    Raises HTTP 401 if there is no authenticated session.
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def require_role(
    allowed_roles: Iterable[str],
) -> Callable[[Mapping[str, str]], Mapping[str, str]]:
    """
    Role-based access control dependency factory.

    Usage:
        @router.get("/dashboard", dependencies=[Depends(require_role([...]))])
        async def dashboard(...):
            ...
    """

    allowed: List[str] = list(allowed_roles)
    allowed_normalized = {normalize_role(role) for role in allowed}

    def dependency(user: Mapping[str, str] = Depends(get_current_user)) -> Mapping[str, str]:
        role: Optional[str] = user.get("role")  # type: ignore[assignment]
        normalized = normalize_role(role)
        if role not in allowed and normalized not in allowed_normalized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return dependency

