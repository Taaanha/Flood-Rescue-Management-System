from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..dependencies import require_role
from ..models import Resource, ResourceCategory, ResourceInventory


templates = Jinja2Templates(directory="frrms/templates")

router = APIRouter()


@router.get("/inventory", response_class=HTMLResponse, name="inventory")
async def inventory_page(
    request: Request,
    _: dict = Depends(require_role(["admin", "coordinator", "field_personnel", "viewer"])),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    inventory_items = (
        db.query(ResourceInventory)
        .options(joinedload(ResourceInventory.resource), joinedload(ResourceInventory.location))
        .order_by(ResourceInventory.id.desc())
        .all()
    )
    resources = db.query(Resource).order_by(Resource.name.asc()).all()
    categories = db.query(ResourceCategory).order_by(ResourceCategory.category_name.asc()).all()
    low_stock_items = [item for item in inventory_items if (item.quantity or 0) < (item.threshold or 0)]

    if inventory_items:
        healthy = sum(1 for row in inventory_items if (row.quantity or 0) >= (row.threshold or 0))
        inventory_percentage = int((healthy * 100) / len(inventory_items))
    else:
        inventory_percentage = 0

    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            "page": "inventory",
            "inventory_percentage": inventory_percentage,
            "inventory_items": inventory_items,
            "low_stock_items": low_stock_items,
            "resources": resources,
            "categories": categories,
        },
    )

