# Order Management API

A small backend service for creating, retrieving and processing orders, built with FastAPI, SQLAlchemy 2, Pydantic v2 and PostgreSQL (SQLite for local development and fast tests).

## Contents

- [Quick start (Docker)](#quick-start-docker)
- [Local development](#local-development)
- [Running tests](#running-tests)
- [API](#api)
- [Project structure](#project-structure)
- [Architectural decisions](#architectural-decisions)
- [Assumptions and limitations](#assumptions-and-limitations)

## Quick start (Docker)

Requires Docker with Compose.

```bash
docker compose up --build
```

This starts PostgreSQL 17 and the API. The API waits until the database passes its health check.

- Interactive API docs (Swagger UI): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

Stop with `docker compose down`. Data is kept in the `pgdata` volume. Use `docker compose down -v` to delete it.

## Local development

Requires Python 3.11+ (developed on 3.12).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

By default the app uses a local SQLite file (`orders.db`). To use another database, set `DATABASE_URL`, either as an environment variable or in a `.env` file:

```bash
DATABASE_URL=postgresql+psycopg://orders:orders@localhost:5432/orders uvicorn app.main:app --reload
```

## Running tests

```bash
pytest
```

By default every test gets a fresh in-memory SQLite database, so the suite runs in well under a second and needs no setup.

To run the same suite against PostgreSQL, using the Compose database:

```bash
docker compose up -d db
docker compose exec db createdb -U orders orders_test
TEST_DATABASE_URL=postgresql+psycopg://orders:orders@localhost:5432/orders_test pytest
```

Tests drop and recreate all tables, so always point `TEST_DATABASE_URL` at a dedicated test database.

### What is covered

| Requirement | Tests |
|---|---|
| Successful order creation | `test_create_order_returns_created_order` |
| Invalid email, price, quantity | `test_create_order_rejects_invalid_*` (parametrized) |
| Empty order | `test_create_order_rejects_empty_order` |
| Nonexistent order | `test_get_nonexistent_order_returns_404` |
| Status updates | `test_update_status_through_full_lifecycle` |
| Invalid status transitions | `test_invalid_status_transition_returns_409`, `test_allowed_transitions` |
| Pagination and filtering | `test_list_orders_*` |
| Database integration | `test_create_order_persists_order_and_items`, `test_database_rejects_negative_price_even_without_pydantic`, `test_invalid_transition_leaves_order_unchanged` |
| Duplicate requests | `test_duplicate_request_with_same_idempotency_key_returns_same_order`, `test_same_status_update_is_a_no_op` |
| Concurrent updates | `test_concurrent_update_is_detected` |
| Monetary precision | `test_calculate_total_is_exact_for_money` |

API tests (`tests/test_api.py`) go through HTTP using FastAPI's `TestClient`. Service tests (`tests/test_order_service.py`) call the business logic directly: pure unit tests, plus integration tests against a real database.

## API

| Method | Path | Description | Success | Errors |
|---|---|---|---|---|
| `POST` | `/orders` | Create an order | 201 | 422 invalid input |
| `GET` | `/orders/{order_id}` | Get one order with its items | 200 | 404 not found |
| `GET` | `/orders` | List orders (paginated, filterable) | 200 | 422 invalid query |
| `PATCH` | `/orders/{order_id}/status` | Change the order status | 200 | 404 not found, 409 invalid transition or concurrent update, 422 unknown status |

### Create an order

```bash
curl -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: 3f6c1c2e-checkout-1" \
  -d '{
        "customer_email": "anna@example.com",
        "items": [
          {"product_name": "Book", "price": "10.10", "quantity": 3},
          {"product_name": "Pen",  "price": "0.20",  "quantity": 1}
        ]
      }'
```

```json
{
  "id": 1,
  "customer_email": "anna@example.com",
  "status": "pending",
  "total_amount": "30.50",
  "created_at": "2026-11-15T13:16:33.108678Z",
  "items": [
    {"id": 1, "product_name": "Book", "price": "10.10", "quantity": 3},
    {"id": 2, "product_name": "Pen", "price": "0.20", "quantity": 1}
  ]
}
```

Validation rules: the email must be valid, there must be at least one item, `price` must be > 0 with at most 2 decimal places, and `quantity` must be a positive integer. The `Idempotency-Key` header is optional.

### List orders

```
GET /orders?status=pending&customer_email=anna@example.com&limit=20&offset=0
```

```json
{"items": [...], "total": 42, "limit": 20, "offset": 0}
```

`limit` is 1–100 (default 20) and `offset` is ≥ 0. Results are sorted newest first.

### Update status

```bash
curl -X PATCH http://127.0.0.1:8000/orders/1/status \
  -H "Content-Type: application/json" \
  -d '{"status": "processing"}'
```

Allowed transitions:

```
pending ──► processing ──► completed
   │             │
   └──► cancelled ◄┘
```

`completed` and `cancelled` are final. Any other transition returns **409 Conflict**, for example:

```json
{"detail": "Cannot change order status from 'completed' to 'cancelled'"}
```

## Project structure

```
app/
├── main.py                  # App setup, router registration, error → HTTP mapping
├── config.py                # Settings from environment variables
├── database.py              # Engine, session factory, get_db dependency
├── models.py                # SQLAlchemy models (Order, OrderItem, OrderStatus)
├── schemas.py               # Pydantic request/response schemas
├── exceptions.py            # Business exceptions (no HTTP knowledge)
├── api/
│   └── orders.py            # HTTP routes: thin, delegate to the service
└── services/
    └── order_service.py     # Business logic: totals, transitions, idempotency, locking
tests/
├── conftest.py              # Fixtures: isolated database per test, test client
├── test_api.py              # Endpoint tests through HTTP
└── test_order_service.py    # Unit and database integration tests
```

## Architectural decisions

### Layered architecture

Requests flow `routes → service → database`, and each layer has one responsibility:

- **Routes** (`app/api`) handle HTTP only: parsing input, choosing the status code, and response shape. They contain no business rules.
- **The service** (`app/services`) holds all business rules and owns transactions. It knows nothing about HTTP; it raises domain exceptions such as `OrderNotFoundError`.
- **`main.py`** maps domain exceptions to HTTP status codes in one exception handler, so routes don't repeat `try/except`.

This keeps the business logic reusable outside HTTP (for example from a background job) and testable without a web server.

### Validation in two layers

- **Pydantic** validates the shape of every request (valid email, at least one item, price > 0, quantity > 0) and returns a 422 listing *all* errors.
- **Database `CHECK` constraints** enforce `price > 0` and `quantity > 0` as a last line of defense against bugs or direct database writes.
- Rules that depend on stored state (status transitions) live in the service, because Pydantic only sees the incoming request.

Separate request schemas (`OrderCreate`) and response schemas (`OrderRead`) keep the API contract independent of the database model. Internal columns (`version`, `idempotency_key`) are never exposed.

### Monetary precision

Money is `Decimal` in Python and `NUMERIC(10, 2)` / `NUMERIC(12, 2)` in the database, never `float`, because binary floating point cannot represent values like 0.1 exactly. Amounts with more than 2 decimal places are rejected rather than silently rounded. The total is calculated on the server and never accepted from the client. Amounts are serialized as JSON strings (`"30.50"`) so clients don't parse them into floats.

### Order status as a state machine

Allowed transitions are declared as data in `ALLOWED_TRANSITIONS`, not as scattered `if` statements. All rules are visible in one place, and adding a status is a one-line change.

### Transactions

Each service operation commits once, so an order and all its items are saved atomically or not at all. On failure the session is rolled back. The `get_db` dependency always closes the session, even when a request fails, so connections can't leak.

### Duplicate requests (idempotency)

- **`POST /orders`** accepts an optional `Idempotency-Key` header. A retry with the same key returns the original order instead of creating a second one. A `UNIQUE` constraint on the key guarantees this even when two identical requests race: the losing insert fails, is rolled back, and the existing order is returned.
- **`PATCH /orders/{id}/status`** is naturally idempotent. Setting the status an order already has is a no-op that returns the order unchanged.

### Concurrent updates (optimistic locking)

`Order` has a `version` column registered as SQLAlchemy's `version_id_col`. Every update runs as `UPDATE ... WHERE id = :id AND version = :read_version` and increments the version. If another request saved first, no row matches, and the API returns **409 Conflict** so the client can re-read and retry. This prevents lost updates, for example a cancel and a process both succeeding based on the same stale `pending` state.

Optimistic locking was chosen because concurrent edits of the same order are expected to be rare. It takes no locks and works the same on SQLite and PostgreSQL. If conflicts were frequent, pessimistic locking (`SELECT ... FOR UPDATE`) would be the alternative.

### Avoiding N+1 queries

`Order.items` uses `lazy="selectin"`, so listing *N* orders loads all their items in one extra query instead of *N* queries.

### Pagination

Offset pagination with a deterministic sort (`created_at DESC, id DESC`), so pages don't repeat or skip rows. The response includes `total` so clients can render page counts. Page size is capped at 100.

### Timestamps

All timestamps are stored and returned in UTC (ISO 8601 with `Z`). The response schema normalizes them, because SQLite drops timezone information and PostgreSQL returns timestamps in the server's local timezone.

### Configuration

All configuration comes from environment variables (12-factor), read by `pydantic-settings`. The same code runs against SQLite locally and PostgreSQL in Docker by changing only `DATABASE_URL`.

### Testing strategy

Each test gets its own empty database, and the app's `get_db` dependency is overridden to use it, so tests are isolated and order-independent. The suite runs on in-memory SQLite by default for speed. It also runs against PostgreSQL via `TEST_DATABASE_URL`, which caught a timezone difference SQLite had hidden.

## Assumptions and limitations

- **Schema management:** tables are created at startup with `create_all`. That's fine for this scope, but it can't alter existing tables. Production would use Alembic migrations.
- **No authentication or authorization.** Any client can read or change any order.
- **Idempotency keys** are stored per order and kept forever. They aren't tied to the request body, so reusing a key with a different payload returns the original order. Production would also store a hash of the payload, reject mismatches with 422, and expire old keys.
- **Orders are immutable after creation** apart from their status. There's no endpoint for editing items, which is why the total is stored rather than recalculated.
- **The `customer_email` filter** is an exact match against the stored address. Email domains are normalized to lowercase on input, but the local part is case-sensitive.
- **Offset pagination** gets slower for very deep pages. Keyset (cursor) pagination would scale better for large datasets.
- **Single currency** is assumed, with 2 decimal places. Amounts are capped by the `NUMERIC` precision: 99,999,999.99 per item price.
- **Concurrent updates return 409** rather than retrying automatically. The client is expected to re-read the order and retry.
- **Synchronous SQLAlchemy** is used for simplicity. FastAPI runs the endpoints in a threadpool. Very high concurrency would warrant async SQLAlchemy with an async driver.
