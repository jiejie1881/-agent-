def test_store_crud(client):
    created = client.post(
        "/api/v1/stores",
        json={"code": "S001", "name": "一号门店", "address": "测试路1号"},
    )
    assert created.status_code == 201
    store_id = created.json()["id"]

    duplicate = client.post(
        "/api/v1/stores", json={"code": "S001", "name": "二号门店"}
    )
    assert duplicate.status_code == 409

    updated = client.patch(
        f"/api/v1/stores/{store_id}", json={"contact_phone": "13800000000"}
    )
    assert updated.status_code == 200
    assert updated.json()["contact_phone"] == "13800000000"


def test_store_route_many_to_many(client):
    terrain = client.post(
        "/api/v1/terrains", json={"code": "STRICT", "name": "严控"}
    ).json()
    route = client.post(
        "/api/v1/routes",
        json={"code": "R001", "name": "严控线路"},
    ).json()
    client.post(
        f"/api/v1/routes/{route['id']}/terrain-configs",
        json={"terrain_id": terrain["id"], "effective_date": "2026-09-24"},
    )
    store = client.post(
        "/api/v1/stores", json={"code": "S001", "name": "交界门店"}
    ).json()

    linked = client.post(
        f"/api/v1/stores/{store['id']}/routes", json={"route_id": route["id"]}
    )
    assert linked.status_code == 201
    assert linked.json()["route"]["name"] == "严控线路"

    duplicate = client.post(
        f"/api/v1/stores/{store['id']}/routes", json={"route_id": route["id"]}
    )
    assert duplicate.status_code == 409

    listed = client.get(f"/api/v1/stores/{store['id']}/routes")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    removed = client.delete(
        f"/api/v1/stores/{store['id']}/routes/{route['id']}"
    )
    assert removed.status_code == 204
