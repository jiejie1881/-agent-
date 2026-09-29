def create_vehicle(client):
    vehicle_type = client.post(
        "/api/v1/vehicle-types",
        json={"code": "SMALL_VAN", "name": "小包", "min_load": 1, "max_load": 300},
    ).json()
    return client.post(
        "/api/v1/vehicles",
        json={
            "code": "V001",
            "plate_number": "粤A10001",
            "vehicle_type_id": vehicle_type["id"],
        },
    ).json()


def test_vehicle_attendance_crud_and_unique_constraint(client):
    vehicle = create_vehicle(client)
    payload = {"date": "2026-09-24", "vehicle_id": vehicle["id"], "available": True}

    created = client.post("/api/v1/vehicle-attendances", json=payload)
    assert created.status_code == 201
    attendance_id = created.json()["id"]
    assert created.json()["vehicle"]["plate_number"] == "粤A10001"

    duplicate = client.post("/api/v1/vehicle-attendances", json=payload)
    assert duplicate.status_code == 409

    updated = client.patch(
        f"/api/v1/vehicle-attendances/{attendance_id}",
        json={"available": False},
    )
    assert updated.status_code == 200
    assert updated.json()["available"] is False

    listed = client.get("/api/v1/vehicle-attendances?date=2026-09-24")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    missing_vehicle = client.post(
        "/api/v1/vehicle-attendances",
        json={"date": "2026-09-24", "vehicle_id": 999, "available": True},
    )
    assert missing_vehicle.status_code == 404
