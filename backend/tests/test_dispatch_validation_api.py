def setup_valid_dispatch_data(client):
    terrain = client.post(
        "/api/v1/terrains", json={"code": "CONTROLLED", "name": "中控"}
    ).json()
    route = client.post(
        "/api/v1/routes", json={"code": "R001", "name": "一号线路"}
    ).json()
    client.post(
        f"/api/v1/routes/{route['id']}/terrain-configs",
        json={"terrain_id": terrain["id"], "effective_date": "2026-09-01"},
    )
    store = client.post(
        "/api/v1/stores", json={"code": "S001", "name": "一号门店"}
    ).json()
    client.post(
        f"/api/v1/stores/{store['id']}/routes", json={"route_id": route["id"]}
    )
    vehicle_type = client.post(
        "/api/v1/vehicle-types",
        json={"code": "BIG_VAN", "name": "大包", "min_load": 300, "max_load": 420},
    ).json()
    client.post(
        f"/api/v1/vehicle-types/{vehicle_type['id']}/terrain-permissions",
        json={"terrain_id": terrain["id"]},
    )
    vehicle = client.post(
        "/api/v1/vehicles",
        json={
            "code": "V001",
            "plate_number": "粤A10001",
            "vehicle_type_id": vehicle_type["id"],
        },
    ).json()
    client.post(
        "/api/v1/vehicle-attendances",
        json={"date": "2026-09-24", "vehicle_id": vehicle["id"], "available": True},
    )
    demand = client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": store["id"],
            "period": "MORNING",
            "quantity": 350,
            "status": "PENDING",
        },
    ).json()
    return vehicle, demand, route


def test_validate_dispatch_returns_legal(client):
    vehicle, demand, route = setup_valid_dispatch_data(client)
    response = client.post(
        "/api/v1/dispatch-validations",
        json={
            "vehicle_id": vehicle["id"],
            "delivery_demand_id": demand["id"],
            "route_id": route["id"],
            "period": "MORNING",
            "quantity": 350,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is True
    assert body["result"] == "合法"
    assert body["failure_reasons"] == []
    assert len(body["constraints"]) == 5
    assert all(item["passed"] for item in body["constraints"])


def test_validate_dispatch_returns_all_failure_reasons(client):
    vehicle, demand, route = setup_valid_dispatch_data(client)
    client.patch(
        f"/api/v1/vehicle-attendances/1", json={"available": False}
    )
    response = client.post(
        "/api/v1/dispatch-validations",
        json={
            "vehicle_id": vehicle["id"],
            "delivery_demand_id": demand["id"],
            "route_id": route["id"],
            "period": "AFTERNOON",
            "quantity": 100,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert body["result"] == "不合法"
    failed = {item["constraint"] for item in body["constraints"] if not item["passed"]}
    assert failed == {
        "VehicleAvailableConstraint",
        "PeriodConstraint",
        "LoadConstraint",
    }
    assert len(body["failure_reasons"]) == 3
