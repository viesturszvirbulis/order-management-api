from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.exceptions import ConcurrentUpdateError, InvalidStatusTransitionError
from app.models import Order, OrderItem, OrderStatus
from app.schemas import OrderCreate, OrderItemCreate
from app.services import order_service


def make_order_data(*prices_and_quantities: tuple[str, int]) -> OrderCreate:
    return OrderCreate(
        customer_email="anna@example.com",
        items=[
            OrderItemCreate(product_name=f"Item {i}", price=Decimal(price), quantity=qty)
            for i, (price, qty) in enumerate(prices_and_quantities)
        ],
    )


# ---------- Unit tests: pure logic, no database ----------

def test_calculate_total_is_exact_for_money() -> None:
    data = make_order_data(("0.10", 1), ("0.20", 1))

    total = order_service.calculate_total(data.items)

    assert total == Decimal("0.30")  # with float this would be 0.30000000000000004


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        (OrderStatus.PENDING, OrderStatus.PROCESSING, True),
        (OrderStatus.PENDING, OrderStatus.CANCELLED, True),
        (OrderStatus.PROCESSING, OrderStatus.COMPLETED, True),
        (OrderStatus.PROCESSING, OrderStatus.CANCELLED, True),
        (OrderStatus.PENDING, OrderStatus.COMPLETED, False),
        (OrderStatus.COMPLETED, OrderStatus.CANCELLED, False),
        (OrderStatus.CANCELLED, OrderStatus.PROCESSING, False),
    ],
)
def test_allowed_transitions(current: OrderStatus, target: OrderStatus, allowed: bool) -> None:
    assert (target in order_service.ALLOWED_TRANSITIONS[current]) is allowed


# ---------- Integration tests: service + real database ----------

def test_create_order_persists_order_and_items(db: Session) -> None:
    order = order_service.create_order(db, make_order_data(("10.10", 3), ("0.20", 1)))

    db.expire_all()  # forget cached objects: force a real read from the database
    stored = db.scalar(select(Order).where(Order.id == order.id))

    assert stored is not None
    assert stored.total_amount == Decimal("30.50")
    assert stored.status == OrderStatus.PENDING
    assert [(i.product_name, i.price, i.quantity) for i in stored.items] == [
        ("Item 0", Decimal("10.10"), 3),
        ("Item 1", Decimal("0.20"), 1),
    ]


def test_database_rejects_negative_price_even_without_pydantic(db: Session) -> None:
    order = order_service.create_order(db, make_order_data(("1.00", 1)))
    db.add(OrderItem(order_id=order.id, product_name="Bad", price=Decimal("-1.00"), quantity=1))

    with pytest.raises(IntegrityError):
        db.commit()


def test_same_status_update_is_a_no_op(db: Session) -> None:
    order = order_service.create_order(db, make_order_data(("1.00", 1)))
    order_service.update_order_status(db, order.id, OrderStatus.PROCESSING)

    again = order_service.update_order_status(db, order.id, OrderStatus.PROCESSING)

    assert again.status == OrderStatus.PROCESSING
    assert again.version == 2  # unchanged by the repeated request


def test_invalid_transition_leaves_order_unchanged(db: Session) -> None:
    order = order_service.create_order(db, make_order_data(("1.00", 1)))
    order_service.update_order_status(db, order.id, OrderStatus.CANCELLED)

    with pytest.raises(InvalidStatusTransitionError):
        order_service.update_order_status(db, order.id, OrderStatus.PROCESSING)

    db.expire_all()
    assert order_service.get_order(db, order.id).status == OrderStatus.CANCELLED


def test_concurrent_update_is_detected(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as setup:
        order_id = order_service.create_order(setup, make_order_data(("1.00", 1))).id

    with session_factory() as request_a, session_factory() as request_b:
        # Both "requests" read the order while it is still pending.
        order_a = order_service.get_order(request_a, order_id)
        order_b = order_service.get_order(request_b, order_id)

        # Request A saves first and wins.
        order_a.status = OrderStatus.PROCESSING
        request_a.commit()

        # Request B still holds the stale "pending" copy and must be rejected.
        assert order_b.status == OrderStatus.PENDING
        with pytest.raises(ConcurrentUpdateError):
            order_service.update_order_status(request_b, order_id, OrderStatus.CANCELLED)
