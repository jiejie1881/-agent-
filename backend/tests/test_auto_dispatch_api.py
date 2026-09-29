def create_terrain_route_and_stores(client, store_quantities):
    terrain = client.post(
        "/api/v1/terrains", json={"code": "NORMAL", "name": "普通"}
    ).json()
    route = client.post(
        "/api/v1/routes", json={"code": "R001", "name": "一号线路"}
    ).json()
    client.post(
        f"/api/v1/routes/{route['id']}/terrain-configs",
        json={"terrain_id": terrain["id"], "effective_date": "2026-09-01"},
    )

    stores = []
    for index, quantity in enumerate(store_quantities, start=1):
        store = client.post(
            "/api/v1/stores",
            json={"code": f"S{index:03}", "name": f"门店{index}"},
        ).json()
        client.post(
            f"/api/v1/stores/{store['id']}/routes",
            json={"route_id": route["id"]},
        )
        demand = client.post(
            "/api/v1/delivery-demands",
            json={
                "date": "2026-09-24",
                "store_id": store["id"],
                "period": "MORNING",
                "quantity": quantity,
                "status": "PENDING",
            },
        ).json()
        stores.append((store, demand))
    return terrain, route, stores


def create_vehicle(client, terrain_id, code, name, min_load, max_load, plate):
    vehicle_type = client.post(
        "/api/v1/vehicle-types",
        json={
            "code": code,
            "name": name,
            "min_load": min_load,
            "max_load": max_load,
        },
    ).json()
    client.post(
        f"/api/v1/vehicle-types/{vehicle_type['id']}/terrain-permissions",
        json={"terrain_id": terrain_id},
    )
    vehicle = client.post(
        "/api/v1/vehicles",
        json={
            "code": f"VEH_{code}",
            "plate_number": plate,
            "vehicle_type_id": vehicle_type["id"],
        },
    ).json()
    client.post(
        "/api/v1/vehicle-attendances",
        json={"date": "2026-09-24", "vehicle_id": vehicle["id"], "available": True},
    )
    return vehicle


def test_auto_dispatch_reuses_vehicle_for_multiple_trips(client):
    terrain, route, _ = create_terrain_route_and_stores(
        client, [350, 350, 200, 200, 650]
    )
    create_vehicle(client, terrain["id"], "FOUR_METER", "四米二", 630, 800, "粤A40001")
    create_vehicle(client, terrain["id"], "BIG_VAN", "大包", 300, 420, "粤A30001")
    create_vehicle(client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "粤A10001")

    response = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"})
    assert response.status_code == 200
    body = response.json()
    assert body["unassigned_demands"] == []
    assert [trip["vehicle"]["vehicle_type_name"] for trip in body["trips"]] == [
        "大包",
        "小包",
        "小包",
        "四米二",
        "大包",
    ]
    assert [trip["vehicle"]["vehicle_type_code"] for trip in body["trips"]] == [
        "BIG_VAN",
        "SMALL_VAN",
        "SMALL_VAN",
        "FOUR_METER",
        "BIG_VAN",
    ]
    assert [trip["trip_no"] for trip in body["trips"]] == [1, 1, 2, 1, 2]
    assert all(trip["period"] == "MORNING" for trip in body["trips"])
    assert all(trip["route"]["id"] == route["id"] for trip in body["trips"])
    assert [trip["total_load"] for trip in body["trips"]] == [
        "350.00",
        "200.00",
        "200.00",
        "650.00",
        "350.00",
    ]
    demand_ids = [
        store["demand_id"]
        for trip in body["trips"]
        for store in trip["stores"]
    ]
    assert len(demand_ids) == len(set(demand_ids)) == 5


def test_vehicle_can_be_used_again_in_next_period(client):
    terrain, route, stores = create_terrain_route_and_stores(client, [100])
    store, _ = stores[0]
    client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": store["id"],
            "period": "AFTERNOON",
            "quantity": 100,
            "status": "PENDING",
        },
    )
    create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "粤A10001"
    )

    response = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"})
    assert response.status_code == 200
    body = response.json()
    assert body["unassigned_demands"] == []
    assert [trip["period"] for trip in body["trips"]] == [
        "MORNING",
        "AFTERNOON",
    ]
    assert [trip["trip_no"] for trip in body["trips"]] == [1, 1]
    assert all(trip["route"]["id"] == route["id"] for trip in body["trips"])


def test_small_van_generates_two_independent_morning_trips(client):
    terrain, _, stores = create_terrain_route_and_stores(client, [100, 100])
    vehicle = create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "粤A10001"
    )

    response = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"})
    assert response.status_code == 200
    body = response.json()
    assert body["unassigned_demands"] == []
    assert [trip["vehicle"]["id"] for trip in body["trips"]] == [
        vehicle["id"],
        vehicle["id"],
    ]
    assert [trip["trip_no"] for trip in body["trips"]] == [1, 2]
    assert [trip["total_load"] for trip in body["trips"]] == ["100.00", "100.00"]

    demand_ids = [
        store["demand_id"]
        for trip in body["trips"]
        for store in trip["stores"]
    ]
    assert set(demand_ids) == {demand["id"] for _, demand in stores}
    assert len(demand_ids) == len(set(demand_ids))

    persisted = client.get(f"/api/v1/dispatch-plans/{body['plan_id']}").json()
    assert [order["trip_no"] for order in persisted["orders"]] == [1, 2]
    assert [order["total_load"] for order in persisted["orders"]] == [
        "100.00",
        "100.00",
    ]


def test_four_meter_vehicle_generates_first_morning_trip(client):
    terrain, _, _ = create_terrain_route_and_stores(client, [650])
    vehicle = create_vehicle(
        client, terrain["id"], "FOUR_METER", "四米二", 630, 800, "粤A40001"
    )

    response = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"})

    assert response.status_code == 200
    assert response.json()["unassigned_demands"] == []
    trip = response.json()["trips"][0]
    assert trip["vehicle"]["id"] == vehicle["id"]
    assert trip["period"] == "MORNING"
    assert trip["trip_no"] == 1
    assert trip["total_load"] == "650.00"


def test_auto_dispatch_returns_unassigned_demand(client):
    terrain, _, _ = create_terrain_route_and_stores(client, [900])
    create_vehicle(client, terrain["id"], "FOUR_METER", "四米二", 630, 800, "粤A40001")

    response = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"})
    assert response.status_code == 200
    body = response.json()
    assert body["trips"] == []
    assert len(body["unassigned_demands"]) == 1
    assert body["unassigned_demands"][0]["reasons"]


def test_auto_dispatch_only_reads_pending_demands(client, session):
    terrain, _, stores = create_terrain_route_and_stores(client, [100, 100, 100])
    pending_demand = stores[0][1]
    cancelled_demand = stores[1][1]
    completed_demand = stores[2][1]

    from app.domain.enums import DeliveryDemandStatus
    from app.models.delivery_demand import DeliveryDemand

    session.get(DeliveryDemand, cancelled_demand["id"]).status = (
        DeliveryDemandStatus.CANCELLED
    )
    session.get(DeliveryDemand, completed_demand["id"]).status = (
        DeliveryDemandStatus.COMPLETED
    )
    session.commit()

    create_vehicle(
        client, terrain["id"], "SMALL_VAN", "小包", 1, 300, "粤A10001"
    )
    response = client.post("/api/v1/auto-dispatch", json={"date": "2026-09-24"})
    assert response.status_code == 200
    body = response.json()
    assigned_demand_ids = {
        store["demand_id"]
        for trip in body["trips"]
        for store in trip["stores"]
    }
    assert assigned_demand_ids == {pending_demand["id"]}
    returned_demand_ids = assigned_demand_ids | {
        item["demand_id"] for item in body["unassigned_demands"]
    }
    assert cancelled_demand["id"] not in returned_demand_ids
    assert completed_demand["id"] not in returned_demand_ids
