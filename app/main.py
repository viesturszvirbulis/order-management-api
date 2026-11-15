from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import orders
from app.config import get_settings
from app.database import Base, engine
from app.exceptions import (
    ConcurrentUpdateError,
    InvalidStatusTransitionError,
    OrderError,
    OrderNotFoundError,
)

ERROR_STATUS_CODES: dict[type[OrderError], int] = {
    OrderNotFoundError: 404,
    InvalidStatusTransitionError: 409,
    ConcurrentUpdateError: 409,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(orders.router)


@app.exception_handler(OrderError)
async def handle_order_error(request: Request, exc: OrderError) -> JSONResponse:
    status_code = ERROR_STATUS_CODES.get(type(exc), 400)
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}