from app.models import OrderStatus


class OrderError(Exception):
    """Base class for all order business errors."""


class OrderNotFoundError(OrderError):
    def __init__(self, order_id: int) -> None:
        self.order_id = order_id
        super().__init__(f"Order {order_id} not found")


class InvalidStatusTransitionError(OrderError):
    def __init__(self, current: OrderStatus, target: OrderStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot change order status from '{current.value}' to '{target.value}'")


class ConcurrentUpdateError(OrderError):
    def __init__(self, order_id: int) -> None:
        self.order_id = order_id
        super().__init__(f"Order {order_id} was modified by another request, please retry")