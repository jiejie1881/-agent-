def create_terrain(client):
    response = client.post(
        "/api/v1/terrains", json={"code": "NORMAL", "name": "普通"}
    )
    return response.json()["id"]


def test_route_crud_and_foreign_key_validation(client):
    terrain_id = create_terrain(client)
    created = client.post(
        "/api/v1/routes",
        json={"code": "R001", "name": "一号线路"},
    )
    assert created.status_code == 201
    route_id = created.json()["id"]

    configured = client.post(
        f"/api/v1/routes/{route_id}/terrain-configs",
        json={"terrain_id": terrain_id, "effective_date": "2026-09-24"},
    )
    assert configured.status_code == 201

    effective = client.get(
        f"/api/v1/routes/{route_id}/effective-terrain?on_date=2026-09-25"
    )
    assert effective.status_code == 200
    assert effective.json()["terrain"]["name"] == "普通"

    config_id = configured.json()["id"]
    updated_config = client.patch(
        f"/api/v1/routes/{route_id}/terrain-configs/{config_id}",
        json={"effective_date": "2026-09-23"},
    )
    assert updated_config.status_code == 200

    missing_terrain = client.post(
        f"/api/v1/routes/{route_id}/terrain-configs",
        json={"terrain_id": 999, "effective_date": "2026-09-25"},
    )
    assert missing_terrain.status_code == 404

    invalid = client.post(
        "/api/v1/routes", json={"code": "", "name": ""}
    )
    assert invalid.status_code == 422

    updated = client.patch(f"/api/v1/routes/{route_id}", json={"name": "主线路"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "主线路"
