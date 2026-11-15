from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.exceptions import ConcurrentUpdateError, InvalidStatusTransitionError, OrderNotFoundError
from app.models import Order, OrderItem, OrderStatus
from app.schemas import OrderCreate, OrderItemCreate

CENT = Decimal("0.01")

ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


def calculate_total(items: Iterable[OrderItemCreate]) -> Decimal:
    total = sum((item.price * item.quantity for item in items), start=Decimal("0"))
    return total.quantize(CENT)


def create_order(db: Session, data: OrderCreate, idempotency_key: str | None = None) -> Order:
    if idempotency_key is not None:
        existing = _find_by_idempotency_key(db, idempotency_key)
        if existing is not None:
            return existing

    order = Order(
        customer_email=str(data.customer_email),
        total_amount=calculate_total(data.items),
        idempotency_key=idempotency_key,
        items=[
            OrderItem(product_name=item.product_name, price=item.price, quantity=item.quantity)
            for item in data.items
        ],
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Another request with the same key won the race: return its order.
        if idempotency_key is not None:
            existing = _find_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return existing
        raise
    return order


def get_order(db: Session, order_id: int) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise OrderNotFoundError(order_id)
    return order


def list_orders(
    db: Session,
    *,
    status: OrderStatus | None = None,
    customer_email: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Order], int]:
    query = select(Order)
    if status is not None:
        query = query.where(Order.status == status)
    if customer_email is not None:
        query = query.where(Order.customer_email == customer_email)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    orders = db.scalars(
        query.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit).offset(offset)
    ).all()
    return list(orders), total


def update_order_status(db: Session, order_id: int, new_status: OrderStatus) -> Order:
    order = get_order(db, order_id)

    if order.status == new_status:
        return order  # repeated request: nothing to change

    if new_status not in ALLOWED_TRANSITIONS[order.status]:
        raise InvalidStatusTransitionError(order.status, new_status)

    order.status = new_status
    try:
        db.commit() # UPDATE orders SET status =..., version =2 WHERE id =1 AND version =1
    except StaleDataError: # 0 rows matched: someone else saved first
        db.rollback()
        raise ConcurrentUpdateError(order_id) from None
    return order


def _find_by_idempotency_key(db: Session, key: str) -> Order | None:
    return db.scalar(select(Order).where(Order.idempotency_key == key))