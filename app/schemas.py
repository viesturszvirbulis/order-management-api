from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import OrderStatus


# ---------- Input: what the client sends ----------

class OrderItemCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    # type | rules
    product_name: Annotated[str, Field(min_length=1, max_length=255)]
    price: Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]
    quantity: Annotated[int, Field(gt=0)]


class OrderCreate(BaseModel):
    customer_email: EmailStr
    items: Annotated[list[OrderItemCreate], Field(min_length=1)]


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


# ---------- Output: what is sent back ----------

class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_name: str
    price: Decimal
    quantity: int


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_email: EmailStr
    status: OrderStatus
    total_amount: Decimal
    created_at: datetime
    items: list[OrderItemRead]
    @field_validator("created_at") # added for UTC timezone handling, otherwise tests catch a timezone inconsistency issue with SQLite and API response
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        # SQLite drops timezone info; we always store UTC, so re-attach it.
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    


class OrderList(BaseModel):
    items: list[OrderRead]
    total: int
    limit: int
    offset: int