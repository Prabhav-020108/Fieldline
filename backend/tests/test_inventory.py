"""
Inventory tests: create / update / delete, validation, RBAC, tenant isolation.

Covers: FR-04 (inventory data the agent reads), NFR-10 (RBAC) and tenant isolation.

    uv run pytest tests/test_inventory.py -v
"""


def _create_item(client, headers, company_id="site-demo", **overrides):
    payload = {
        "part_number": "LC1D18",
        "name": "Schneider contactor",
        "location": "bin 14C, site store room",
        "quantity": 3,
    }
    payload.update(overrides)
    response = client.post(f"/companies/{company_id}/inventory", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_inventory_list_starts_empty(client):
    response = client.get("/companies/site-demo/inventory")
    assert response.status_code == 200
    assert response.json() == []


def test_create_inventory_requires_login(client):
    response = client.post(
        "/companies/site-demo/inventory",
        json={"part_number": "X1", "name": "Thing", "location": "bin 1"},
    )
    assert response.status_code == 401


def test_create_inventory_item_and_list_it(client, auth_headers, sync_calls):
    item = _create_item(client, auth_headers("technician"))

    assert item["part_number"] == "LC1D18"
    assert item["quantity"] == 3
    assert item["company_id"] == "site-demo"
    assert sync_calls == ["site-demo"]

    listed = client.get("/companies/site-demo/inventory").json()
    assert [i["id"] for i in listed] == [item["id"]]


def test_quantity_defaults_to_zero(client, auth_headers):
    response = client.post(
        "/companies/site-demo/inventory",
        json={"part_number": "X1", "name": "Thing", "location": "bin 1"},
        headers=auth_headers("technician"),
    )
    assert response.status_code == 201
    assert response.json()["quantity"] == 0


def test_inventory_validation_errors_return_422(client, auth_headers):
    headers = auth_headers("technician")
    url = "/companies/site-demo/inventory"
    base = {"part_number": "X1", "name": "Thing", "location": "bin 1"}

    assert client.post(url, json={**base, "quantity": -1}, headers=headers).status_code == 422
    assert (
        client.post(url, json={**base, "quantity": 1_000_001}, headers=headers).status_code == 422
    )
    assert client.post(url, json={**base, "part_number": ""}, headers=headers).status_code == 422
    assert client.post(url, json={"name": "Thing"}, headers=headers).status_code == 422


def test_update_inventory_item(client, auth_headers):
    headers = auth_headers("technician")
    item = _create_item(client, headers)

    response = client.put(
        f"/companies/site-demo/inventory/{item['id']}",
        json={
            "part_number": "LC1D18",
            "name": "Schneider contactor",
            "location": "bin 20A, main warehouse",
            "quantity": 1,
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["location"] == "bin 20A, main warehouse"
    assert response.json()["quantity"] == 1


def test_update_unknown_inventory_item_returns_404(client, auth_headers):
    response = client.put(
        "/companies/site-demo/inventory/no-such-item",
        json={"part_number": "X1", "name": "Thing", "location": "bin 1"},
        headers=auth_headers("technician"),
    )
    assert response.status_code == 404


def test_a_technician_cannot_delete_inventory(client, auth_headers):
    item = _create_item(client, auth_headers("technician"))

    response = client.delete(
        f"/companies/site-demo/inventory/{item['id']}", headers=auth_headers("technician")
    )

    assert response.status_code == 403
    assert len(client.get("/companies/site-demo/inventory").json()) == 1


def test_supervisor_and_dispatcher_can_delete_inventory(client, auth_headers):
    for role in ("supervisor", "dispatcher"):
        item = _create_item(client, auth_headers("technician"))
        response = client.delete(
            f"/companies/site-demo/inventory/{item['id']}", headers=auth_headers(role)
        )
        assert response.status_code == 204, f"{role} should be allowed to delete"

    assert client.get("/companies/site-demo/inventory").json() == []


def test_delete_unknown_inventory_item_returns_404(client, auth_headers):
    response = client.delete(
        "/companies/site-demo/inventory/no-such-item", headers=auth_headers("dispatcher")
    )
    assert response.status_code == 404


def test_inventory_is_isolated_between_companies(client, auth_headers):
    _create_item(client, auth_headers("technician"), part_number="LC1D18")
    _create_item(
        client,
        auth_headers("technician", company_id="acme-elevator"),
        company_id="acme-elevator",
        part_number="GOV-OS-200",
    )

    demo = client.get("/companies/site-demo/inventory").json()
    acme = client.get("/companies/acme-elevator/inventory").json()

    assert [i["part_number"] for i in demo] == ["LC1D18"]
    assert [i["part_number"] for i in acme] == ["GOV-OS-200"]


def test_cannot_add_inventory_to_another_company(client, auth_headers):
    response = client.post(
        "/companies/site-demo/inventory",
        json={"part_number": "X1", "name": "Thing", "location": "bin 1"},
        headers=auth_headers("dispatcher", company_id="acme-elevator"),
    )
    assert response.status_code == 403
