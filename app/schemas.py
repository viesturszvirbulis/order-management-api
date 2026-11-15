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
    # SQLite drops the timezone, Postgres returns the server's local timezone.
    # We always store UTC, so normalise every timestamp to UTC.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC) # SQLite case
        return value.astimezone(UTC) # Postgres case

    


class OrderList(BaseModel):
    items: list[OrderRead]
    total: int
    limit: int
    offset: int