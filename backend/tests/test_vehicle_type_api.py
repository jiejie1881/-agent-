def test_vehicle_type_crud_and_load_validation(client):
    created = client.post(
        "/api/v1/vehicle-types",
        json={"code": "FOUR_METER", "name": "四米二", "min_load": 630, "max_load": 800},
    )
    assert created.status_code == 201
    vehicle_type_id = created.json()["id"]

    invalid = client.post(
        "/api/v1/vehicle-types",
        json={"code": "BIG_VAN", "name": "错误类型", "min_load": 500, "max_load": 300},
    )
    assert invalid.status_code == 422

    invalid_update = client.patch(
        f"/api/v1/vehicle-types/{vehicle_type_id}", json={"min_load": 900}
    )
    assert invalid_update.status_code == 409

    updated = client.patch(
        f"/api/v1/vehicle-types/{vehicle_type_id}", json={"max_load": 820}
    )
    assert updated.status_code == 200
    assert updated.json()["code"] == "FOUR_METER"
    assert updated.json()["max_load"] == "820.00"


def test_vehicle_type_rejects_unknown_code(client):
    response = client.post(
        "/api/v1/vehicle-types",
        json={"code": "OTHER", "name": "其他车型", "min_load": 1, "max_load": 100},
    )

    assert response.status_code == 422


def test_vehicle_type_cannot_be_deleted_when_used(client):
    vehicle_type = client.post(
        "/api/v1/vehicle-types",
        json={"code": "SMALL_VAN", "name": "小包", "min_load": 1, "max_load": 300},
    ).json()
    client.post(
        "/api/v1/vehicles",
        json={"code": "V001", "plate_number": "粤A12345", "vehicle_type_id": vehicle_type["id"]},
    )
    response = client.delete(f"/api/v1/vehicle-types/{vehicle_type['id']}")
    assert response.status_code == 409
