from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient

# helper, removes the boilerplate of creating an order and asserting that it was created successfully
def create_order(client: TestClient, payload: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    body = {**payload, **overrides}
    response = client.post("/orders", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------- POST /orders ----------

def test_create_order_returns_created_order(client: TestClient, order_payload: dict) -> None:
    response = client.post("/orders", json=order_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["customer_email"] == "anna@example.com"
    assert body["status"] == "pending"
    assert body["total_amount"] == "30.50"  # 10.10 * 3 + 0.20 * 1
    assert len(body["items"]) == 2
    assert body["items"][0] == {"id": 1, "product_name": "Book", "price": "10.10", "quantity": 3}


@pytest.mark.parametrize("email", ["not-an-email", "missing-at.com", "a@", ""])
def test_create_order_rejects_invalid_email(client: TestClient, order_payload: dict, email: str) -> None:
    order_payload["customer_email"] = email

    response = client.post("/orders", json=order_payload)

    assert response.status_code == 422


@pytest.mark.parametrize("price", ["0", "-1.00", "1.999", "abc"])
def test_create_order_rejects_invalid_price(client: TestClient, order_payload: dict, price: str) -> None:
    order_payload["items"][0]["price"] = price

    response = client.post("/orders", json=order_payload)

    assert response.status_code == 422


@pytest.mark.parametrize("quantity", [0, -1, 1.5])
def test_create_order_rejects_invalid_quantity(client: TestClient, order_payload: dict, quantity: Any) -> None:
    order_payload["items"][0]["quantity"] = quantity

    response = client.post("/orders", json=order_payload)

    assert response.status_code == 422


def test_create_order_rejects_empty_order(client: TestClient, order_payload: dict) -> None:
    order_payload["items"] = []

    response = client.post("/orders", json=order_payload)

    assert response.status_code == 422


def test_duplicate_request_with_same_idempotency_key_returns_same_order(
    client: TestClient, order_payload: dict
) -> None:
    headers = {"Idempotency-Key": "checkout-123"}

    first = client.post("/orders", json=order_payload, headers=headers)
    second = client.post("/orders", json=order_payload, headers=headers)

    assert first.json()["id"] == second.json()["id"]
    assert client.get("/orders").json()["total"] == 1


# ---------- GET /orders/{id} ----------

def test_get_order_returns_order_with_items(client: TestClient, order_payload: dict) -> None:
    created = create_order(client, order_payload)

    response = client.get(f"/orders/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_nonexistent_order_returns_404(client: TestClient) -> None:
    response = client.get("/orders/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Order 999 not found"}


# ---------- PATCH /orders/{id}/status ----------

def test_update_status_through_full_lifecycle(client: TestClient, order_payload: dict) -> None:
    order_id = create_order(client, order_payload)["id"]

    for new_status in ["processing", "completed"]:
        response = client.patch(f"/orders/{order_id}/status", json={"status": new_status})
        assert response.status_code == 200
        assert response.json()["status"] == new_status


@pytest.mark.parametrize(
    ("path", "forbidden"),
    [
        (["processing", "completed"], "cancelled"),  # completed order cannot be cancelled
        (["cancelled"], "processing"),               # cancelled order cannot be processed
        ([], "completed"),                           # pending cannot skip processing
    ],
)
def test_invalid_status_transition_returns_409(
    client: TestClient, order_payload: dict, path: list[str], forbidden: str
) -> None:
    order_id = create_order(client, order_payload)["id"]
    for status in path:
        client.patch(f"/orders/{order_id}/status", json={"status": status})

    response = client.patch(f"/orders/{order_id}/status", json={"status": forbidden})

    assert response.status_code == 409
    assert "Cannot change order status" in response.json()["detail"]


def test_update_status_of_nonexistent_order_returns_404(client: TestClient) -> None:
    response = client.patch("/orders/999/status", json={"status": "processing"})

    assert response.status_code == 404


def test_update_status_rejects_unknown_status(client: TestClient, order_payload: dict) -> None:
    order_id = create_order(client, order_payload)["id"]

    response = client.patch(f"/orders/{order_id}/status", json={"status": "shipped"})

    assert response.status_code == 422


# ---------- GET /orders ----------

def test_list_orders_paginates(client: TestClient, order_payload: dict) -> None:
    ids = [create_order(client, order_payload)["id"] for _ in range(5)]

    page1 = client.get("/orders", params={"limit": 2, "offset": 0}).json()
    page3 = client.get("/orders", params={"limit": 2, "offset": 4}).json()

    assert page1["total"] == 5
    assert [o["id"] for o in page1["items"]] == [ids[4], ids[3]]  # newest first
    assert [o["id"] for o in page3["items"]] == [ids[0]]


def test_list_orders_filters_by_status(client: TestClient, order_payload: dict) -> None:
    first = create_order(client, order_payload)["id"]
    create_order(client, order_payload)
    client.patch(f"/orders/{first}/status", json={"status": "processing"})

    body = client.get("/orders", params={"status": "processing"}).json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == first


def test_list_orders_filters_by_customer_email(client: TestClient, order_payload: dict) -> None:
    create_order(client, order_payload)
    bob = create_order(client, deepcopy(order_payload), customer_email="bob@example.com")

    body = client.get("/orders", params={"customer_email": "bob@example.com"}).json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == bob["id"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_orders_rejects_invalid_pagination(client: TestClient, params: dict) -> None:
    assert client.get("/orders", params=params).status_code == 422
