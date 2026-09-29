def create_store(client):
    return client.post(
        "/api/v1/stores", json={"code": "S001", "name": "一号门店"}
    ).json()


def test_delivery_demand_crud_period_and_quantity_validation(client):
    store = create_store(client)
    payload = {
        "date": "2026-09-24",
        "store_id": store["id"],
        "period": "MORNING",
        "quantity": 120.5,
        "status": "PENDING",
    }
    created = client.post("/api/v1/delivery-demands", json=payload)
    assert created.status_code == 201
    demand_id = created.json()["id"]
    assert created.json()["store"]["name"] == "一号门店"

    duplicate = client.post("/api/v1/delivery-demands", json=payload)
    assert duplicate.status_code == 409

    invalid_period = client.post(
        "/api/v1/delivery-demands", json={**payload, "period": "EVENING"}
    )
    assert invalid_period.status_code == 422

    invalid_quantity = client.post(
        "/api/v1/delivery-demands",
        json={**payload, "period": "AFTERNOON", "quantity": 0},
    )
    assert invalid_quantity.status_code == 422

    updated = client.patch(
        f"/api/v1/delivery-demands/{demand_id}",
        json={"quantity": 150},
    )
    assert updated.status_code == 200
    assert updated.json()["quantity"] == "150.00"
    assert updated.json()["status"] == "PENDING"

    listed = client.get(
        "/api/v1/delivery-demands?date=2026-09-24&period=MORNING"
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    missing_store = client.post(
        "/api/v1/delivery-demands",
        json={**payload, "store_id": 999, "period": "AFTERNOON"},
    )
    assert missing_store.status_code == 404
