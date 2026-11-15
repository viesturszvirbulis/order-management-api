from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderStatus
from app.schemas import OrderCreate, OrderList, OrderRead, OrderStatusUpdate
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=OrderRead, status_code=201)
def create_order(
    payload: OrderCreate,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(max_length=255)] = None,
) -> Order:
    return order_service.create_order(db, payload, idempotency_key)


@router.get("", response_model=OrderList)
def list_orders(
    db: DbSession,
    status: OrderStatus | None = None,
    customer_email: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderList:
    orders, total = order_service.list_orders(
        db, status=status, customer_email=customer_email, limit=limit, offset=offset
    )
    return OrderList(
        items=[OrderRead.model_validate(order) for order in orders],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: int, db: DbSession) -> Order:
    return order_service.get_order(db, order_id)


@router.patch("/{order_id}/status", response_model=OrderRead)
def update_order_status(order_id: int, payload: OrderStatusUpdate, db: DbSession) -> Order:
    return order_service.update_order_status(db, order_id, payload.status)