"""
Safety-procedure tests. These are the most safety-critical records in the
system (the voice agent reads them back word for word), so only a
supervisor or dispatcher may change them.

Covers: FR-02 (the data behind safety_procedure), NFR-10 (RBAC) and tenant isolation.

    uv run pytest tests/test_safety_procedures.py -v
"""

PANEL_B_TEXT = (
    "Section 4.2 - Panel B Lockout: (1) Notify affected personnel before "
    "de-energizing. (2) Shut down the equipment using the normal stop procedure."
)


def _payload(**overrides):
    payload = {
        "equipment_type": "panel-b",
        "section": "4.2",
        "text": PANEL_B_TEXT,
        "source_manual": "Site Electrical Safety Manual",
    }
    payload.update(overrides)
    return payload


def _create(client, headers, company_id="site-demo", **overrides):
    response = client.post(
        f"/companies/{company_id}/safety-procedures", json=_payload(**overrides), headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_safety_list_is_public_and_starts_empty(client):
    response = client.get("/companies/site-demo/safety-procedures")
    assert response.status_code == 200
    assert response.json() == []


def test_create_requires_login(client):
    response = client.post("/companies/site-demo/safety-procedures", json=_payload())
    assert response.status_code == 401


def test_a_technician_cannot_create_a_safety_procedure(client, auth_headers):
    response = client.post(
        "/companies/site-demo/safety-procedures",
        json=_payload(),
        headers=auth_headers("technician"),
    )
    assert response.status_code == 403
    assert client.get("/companies/site-demo/safety-procedures").json() == []


def test_supervisor_and_dispatcher_can_create_a_procedure(client, auth_headers, sync_calls):
    supervisor_made = _create(client, auth_headers("supervisor"), section="4.2")
    dispatcher_made = _create(
        client, auth_headers("dispatcher"), equipment_type="panel-a", section="4.1"
    )

    assert supervisor_made["text"] == PANEL_B_TEXT  # stored exactly as sent
    assert supervisor_made["source_manual"] == "Site Electrical Safety Manual"
    assert dispatcher_made["section"] == "4.1"
    assert sync_calls == ["site-demo", "site-demo"]

    listed = client.get("/companies/site-demo/safety-procedures").json()
    assert {p["section"] for p in listed} == {"4.1", "4.2"}


def test_source_manual_defaults_when_not_provided(client, auth_headers):
    payload = _payload()
    del payload["source_manual"]
    response = client.post(
        "/companies/site-demo/safety-procedures",
        json=payload,
        headers=auth_headers("supervisor"),
    )
    assert response.status_code == 201
    assert response.json()["source_manual"] == "Site Safety Manual"


def test_safety_validation_errors_return_422(client, auth_headers):
    headers = auth_headers("supervisor")
    url = "/companies/site-demo/safety-procedures"

    assert client.post(url, json=_payload(text=""), headers=headers).status_code == 422
    assert client.post(url, json=_payload(section="x" * 21), headers=headers).status_code == 422
    assert client.post(url, json=_payload(text="x" * 8001), headers=headers).status_code == 422
    assert client.post(url, json=_payload(equipment_type=""), headers=headers).status_code == 422


def test_update_procedure_requires_supervisor_or_dispatcher(client, auth_headers):
    proc = _create(client, auth_headers("supervisor"))
    url = f"/companies/site-demo/safety-procedures/{proc['id']}"
    new_text = "Section 4.2 - Panel B Lockout: (1) Revised step one."

    denied = client.put(url, json=_payload(text=new_text), headers=auth_headers("technician"))
    assert denied.status_code == 403

    allowed = client.put(url, json=_payload(text=new_text), headers=auth_headers("supervisor"))
    assert allowed.status_code == 200
    assert allowed.json()["text"] == new_text


def test_update_unknown_procedure_returns_404(client, auth_headers):
    response = client.put(
        "/companies/site-demo/safety-procedures/no-such-proc",
        json=_payload(),
        headers=auth_headers("supervisor"),
    )
    assert response.status_code == 404


def test_delete_procedure_requires_supervisor_or_dispatcher(client, auth_headers):
    proc = _create(client, auth_headers("supervisor"))
    url = f"/companies/site-demo/safety-procedures/{proc['id']}"

    assert client.delete(url, headers=auth_headers("technician")).status_code == 403
    assert len(client.get("/companies/site-demo/safety-procedures").json()) == 1

    assert client.delete(url, headers=auth_headers("dispatcher")).status_code == 204
    assert client.get("/companies/site-demo/safety-procedures").json() == []


def test_delete_unknown_procedure_returns_404(client, auth_headers):
    response = client.delete(
        "/companies/site-demo/safety-procedures/no-such-proc",
        headers=auth_headers("supervisor"),
    )
    assert response.status_code == 404


def test_safety_procedures_are_isolated_between_companies(client, auth_headers):
    _create(client, auth_headers("supervisor"))
    _create(
        client,
        auth_headers("supervisor", company_id="acme-elevator"),
        company_id="acme-elevator",
        equipment_type="traction-lift",
        section="3.1",
    )

    demo = client.get("/companies/site-demo/safety-procedures").json()
    acme = client.get("/companies/acme-elevator/safety-procedures").json()

    assert [p["equipment_type"] for p in demo] == ["panel-b"]
    assert [p["equipment_type"] for p in acme] == ["traction-lift"]


def test_cannot_write_safety_procedures_for_another_company(client, auth_headers):
    response = client.post(
        "/companies/site-demo/safety-procedures",
        json=_payload(),
        headers=auth_headers("supervisor", company_id="acme-elevator"),
    )
    assert response.status_code == 403
