def test_vehicle_crud_and_vehicle_type_validation(client):
    vehicle_type = client.post(
        "/api/v1/vehicle-types",
        json={"code": "BIG_VAN", "name": "大包", "min_load": 300, "max_load": 420},
    ).json()

    created = client.post(
        "/api/v1/vehicles",
        json={"code": "v001", "plate_number": "粤a12345", "vehicle_type_id": vehicle_type["id"]},
    )
    assert created.status_code == 201
    assert created.json()["code"] == "V001"
    assert created.json()["plate_number"] == "粤A12345"
    vehicle_id = created.json()["id"]

    duplicate = client.post(
        "/api/v1/vehicles",
        json={"code": "V002", "plate_number": "粤A12345", "vehicle_type_id": vehicle_type["id"]},
    )
    assert duplicate.status_code == 409

    missing_type = client.post(
        "/api/v1/vehicles",
        json={"code": "V003", "plate_number": "粤A99999", "vehicle_type_id": 999},
    )
    assert missing_type.status_code == 404

    updated = client.patch(f"/api/v1/vehicles/{vehicle_id}", json={"is_active": False})
    assert updated.status_code == 200
    assert updated.json()["is_active"] is False
