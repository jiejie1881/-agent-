from tests.test_auto_dispatch_api import create_terrain_route_and_stores


def create_small_vans(client, terrain_id, count=2):
    vehicle_type = client.post(
        "/api/v1/vehicle-types",
        json={
            "code": "SMALL_VAN",
            "name": "小包",
            "min_load": 1,
            "max_load": 300,
        },
    ).json()
    client.post(
        f"/api/v1/vehicle-types/{vehicle_type['id']}/terrain-permissions",
        json={"terrain_id": terrain_id},
    )
    vehicles = []
    for index in range(1, count + 1):
        vehicle = client.post(
            "/api/v1/vehicles",
            json={
                "code": f"SV{index}",
                "plate_number": f"湘A0000{index}",
                "vehicle_type_id": vehicle_type["id"],
            },
        ).json()
        attendance = client.post(
            "/api/v1/vehicle-attendances",
            json={
                "date": "2026-09-24",
                "vehicle_id": vehicle["id"],
                "available": True,
            },
        ).json()
        vehicles.append((vehicle, attendance))
    return vehicle_type, vehicles


def generate_adjustable_plan(client, quantities, vehicle_count=2):
    terrain, route, stores = create_terrain_route_and_stores(client, quantities)
    vehicle_type, vehicles = create_small_vans(
        client, terrain["id"], count=vehicle_count
    )
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    plan = client.get(f"/api/v1/dispatch-plans/{generated['plan_id']}").json()
    return generated, plan, stores, vehicle_type, vehicles, terrain, route


def generate_two_route_plan(client):
    terrain = client.post(
        "/api/v1/terrains", json={"code": "NORMAL", "name": "普通"}
    ).json()
    routes = []
    demands = []
    for index in (1, 2):
        route = client.post(
            "/api/v1/routes",
            json={"code": f"R{index:03}", "name": f"{index}号线路"},
        ).json()
        client.post(
            f"/api/v1/routes/{route['id']}/terrain-configs",
            json={"terrain_id": terrain["id"], "effective_date": "2026-09-01"},
        )
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
                "quantity": 100,
            },
        ).json()
        routes.append(route)
        demands.append(demand)
    vehicle_type, vehicles = create_small_vans(client, terrain["id"], count=1)
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    plan = client.get(f"/api/v1/dispatch-plans/{generated['plan_id']}").json()
    return generated, plan, terrain, routes, demands, vehicle_type, vehicles


def move_payload(source, target, demand_id):
    return {
        "delivery_demand_id": demand_id,
        "source_order_id": source["id"],
        "target_order_id": target["id"],
    }


def test_move_demand_between_draft_orders_revalidates_and_persists(client):
    generated, plan, stores, _, vehicles, _, _ = generate_adjustable_plan(
        client, [100, 100, 50, 50]
    )
    source = next(order for order in plan["orders"] if len(order["details"]) == 2)
    target_vehicle_id = vehicles[1][0]["id"]
    target = next(
        order for order in plan["orders"] if order["vehicle"]["id"] == target_vehicle_id
    )
    moved_demand_id = source["details"][0]["delivery_demand_id"]

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(source, target, moved_demand_id),
    )

    assert response.status_code == 200
    body = response.json()
    updated_source = next(order for order in body["orders"] if order["id"] == source["id"])
    updated_target = next(order for order in body["orders"] if order["id"] == target["id"])
    assert updated_source["total_load"] == "50.00"
    assert updated_target["total_load"] == "150.00"
    assert moved_demand_id not in {
        item["delivery_demand_id"] for item in updated_source["details"]
    }
    assert moved_demand_id in {
        item["delivery_demand_id"] for item in updated_target["details"]
    }
    all_ids = [
        item["delivery_demand_id"]
        for order in body["orders"]
        for item in order["details"]
    ]
    assert len(all_ids) == len(set(all_ids)) == len(stores)


def test_target_overload_rejects_move_and_rolls_back(client):
    generated, plan, *_ = generate_adjustable_plan(client, [250, 100, 100, 100])
    source = next(order for order in plan["orders"] if len(order["details"]) == 2)
    target = next(order for order in plan["orders"] if order["total_load"] == "250.00")
    demand_id = source["details"][0]["delivery_demand_id"]

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(source, target, demand_id),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "TARGET_VEHICLE_OVERLOAD"
    assert "TARGET_VEHICLE_OVERLOAD" in {
        issue["code"] for issue in response.json()["issues"]
    }
    unchanged = client.get(
        f"/api/v1/dispatch-plans/{generated['plan_id']}"
    ).json()
    unchanged_source = next(
        order for order in unchanged["orders"] if order["id"] == source["id"]
    )
    unchanged_target = next(
        order for order in unchanged["orders"] if order["id"] == target["id"]
    )
    assert unchanged_source["total_load"] == source["total_load"]
    assert unchanged_target["total_load"] == target["total_load"]
    assert demand_id in {
        item["delivery_demand_id"] for item in unchanged_source["details"]
    }


def test_source_below_minimum_rejects_move(client):
    generated, plan, *_ = generate_adjustable_plan(client, [100, 100])
    source, target = plan["orders"]
    demand_id = source["details"][0]["delivery_demand_id"]

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(source, target, demand_id),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_BELOW_MIN_LOAD"
    unchanged = client.get(
        f"/api/v1/dispatch-plans/{generated['plan_id']}"
    ).json()
    assert [order["total_load"] for order in unchanged["orders"]] == [
        "100.00",
        "100.00",
    ]


def test_published_plan_cannot_be_manually_adjusted(client):
    generated, plan, *_ = generate_adjustable_plan(client, [100, 100])
    source, target = plan["orders"]
    assert client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/publish"
    ).status_code == 200

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(
            source, target, source["details"][0]["delivery_demand_id"]
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PLAN_NOT_DRAFT"


def test_period_mismatch_is_reported_by_existing_constraint(client):
    terrain, route, stores = create_terrain_route_and_stores(client, [100])
    store, morning_demand = stores[0]
    afternoon_demand = client.post(
        "/api/v1/delivery-demands",
        json={
            "date": "2026-09-24",
            "store_id": store["id"],
            "period": "AFTERNOON",
            "quantity": 100,
        },
    ).json()
    create_small_vans(client, terrain["id"], count=1)
    generated = client.post(
        "/api/v1/auto-dispatch", json={"date": "2026-09-24"}
    ).json()
    plan = client.get(f"/api/v1/dispatch-plans/{generated['plan_id']}").json()
    source = next(order for order in plan["orders"] if order["period"] == "MORNING")
    target = next(order for order in plan["orders"] if order["period"] == "AFTERNOON")

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(source, target, morning_demand["id"]),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PERIOD_MISMATCH"
    assert afternoon_demand["id"] in {
        item["delivery_demand_id"] for item in target["details"]
    }
    assert target["route"]["id"] == route["id"]


def test_unavailable_target_vehicle_is_rejected(client):
    generated, plan, _, _, vehicles, _, _ = generate_adjustable_plan(
        client, [100, 100, 50, 50]
    )
    source = next(order for order in plan["orders"] if len(order["details"]) == 2)
    target_vehicle, target_attendance = vehicles[1]
    target = next(
        order for order in plan["orders"] if order["vehicle"]["id"] == target_vehicle["id"]
    )
    assert client.patch(
        f"/api/v1/vehicle-attendances/{target_attendance['id']}",
        json={"available": False},
    ).status_code == 200

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(
            source, target, source["details"][0]["delivery_demand_id"]
        ),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "TARGET_VEHICLE_NOT_AVAILABLE"


def test_target_route_not_allowed_is_rejected(client):
    generated, plan, _, _, demands, _, _ = generate_two_route_plan(client)
    source = next(
        order
        for order in plan["orders"]
        if order["details"][0]["delivery_demand_id"] == demands[0]["id"]
    )
    target = next(order for order in plan["orders"] if order["id"] != source["id"])

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(source, target, demands[0]["id"]),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ROUTE_NOT_ALLOWED"
    assert {issue["code"] for issue in response.json()["issues"]} == {
        "ROUTE_NOT_ALLOWED",
        "SOURCE_BELOW_MIN_LOAD",
    }


def test_target_terrain_not_allowed_is_rejected(client):
    generated, plan, terrain, _, demands, vehicle_type, _ = generate_two_route_plan(
        client
    )
    source = next(
        order
        for order in plan["orders"]
        if order["details"][0]["delivery_demand_id"] == demands[0]["id"]
    )
    target = next(order for order in plan["orders"] if order["id"] != source["id"])
    assert client.delete(
        f"/api/v1/vehicle-types/{vehicle_type['id']}/terrain-permissions/{terrain['id']}"
    ).status_code == 204

    response = client.post(
        f"/api/v1/dispatch-plans/{generated['plan_id']}/move-demand",
        json=move_payload(source, target, demands[0]["id"]),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "TERRAIN_NOT_ALLOWED"
