def test_terrain_crud_and_validation(client):
    created = client.post(
        "/api/v1/terrains",
        json={"code": "NORMAL", "name": "普通", "description": "所有车辆可通行"},
    )
    assert created.status_code == 201
    terrain_id = created.json()["id"]

    duplicate = client.post(
        "/api/v1/terrains", json={"code": "NORMAL", "name": "其他"}
    )
    assert duplicate.status_code == 409

    invalid = client.post("/api/v1/terrains", json={"code": "", "name": ""})
    assert invalid.status_code == 422

    updated = client.patch(
        f"/api/v1/terrains/{terrain_id}", json={"description": "已更新"}
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "已更新"

    listed = client.get("/api/v1/terrains")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    deleted = client.delete(f"/api/v1/terrains/{terrain_id}")
    assert deleted.status_code == 204
