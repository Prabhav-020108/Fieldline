"""
Comprehensive cross-tenant isolation tests.
Guarantees that a user authenticated in Company A cannot create, modify,
delete, or trigger actions on resources belonging to Company B across ALL endpoint groups.
"""



def test_cannot_create_job_for_another_company(client, auth_headers):
    demo_headers = auth_headers("technician", company_id="site-demo")
    # site-demo technician attempts to create job in acme-elevator
    resp = client.post(
        "/companies/acme-elevator/jobs",
        json={"equipment_id": "unit-12", "fault_description": "Illegal creation"},
        headers=demo_headers,
    )
    assert resp.status_code == 403


def test_cannot_modify_or_delete_another_companys_job(client, auth_headers):
    acme_headers = auth_headers("supervisor", company_id="acme-elevator")
    create_resp = client.post(
        "/companies/acme-elevator/jobs",
        json={"equipment_id": "unit-99", "fault_description": "Elevator cable repair"},
        headers=acme_headers,
    )
    assert create_resp.status_code == 201
    job_id = create_resp.json()["id"]

    demo_headers = auth_headers("supervisor", company_id="site-demo")

    # Attempt to update acme's job with demo credentials -> 403
    update_resp = client.put(
        f"/companies/acme-elevator/jobs/{job_id}",
        json={
            "equipment_id": "unit-99",
            "fault_description": "Elevator cable repair",
            "status": "closed",
            "resolution": "Done",
        },
        headers=demo_headers,
    )
    assert update_resp.status_code == 403

    # Attempt to delete acme's job with demo credentials -> 403
    delete_resp = client.delete(
        f"/companies/acme-elevator/jobs/{job_id}",
        headers=demo_headers,
    )
    assert delete_resp.status_code == 403


def test_cannot_create_modify_or_delete_another_companys_inventory(client, auth_headers):
    acme_headers = auth_headers("supervisor", company_id="acme-elevator")
    create_resp = client.post(
        "/companies/acme-elevator/inventory",
        json={"name": "Traction Sheave", "part_number": "TS-400", "location": "Warehouse A", "quantity": 3},
        headers=acme_headers,
    )
    assert create_resp.status_code == 201
    item_id = create_resp.json()["id"]

    demo_headers = auth_headers("supervisor", company_id="site-demo")

    # Cannot create inventory in acme
    create_illegal = client.post(
        "/companies/acme-elevator/inventory",
        json={"name": "Cable", "part_number": "CB-10", "location": "Warehouse A", "quantity": 1},
        headers=demo_headers,
    )
    assert create_illegal.status_code == 403

    # Cannot modify acme inventory
    patch_resp = client.put(
        f"/companies/acme-elevator/inventory/{item_id}",
        json={"name": "Traction Sheave", "part_number": "TS-400", "location": "Warehouse B", "quantity": 10},
        headers=demo_headers,
    )
    assert patch_resp.status_code == 403

    # Cannot delete acme inventory
    del_resp = client.delete(
        f"/companies/acme-elevator/inventory/{item_id}",
        headers=demo_headers,
    )
    assert del_resp.status_code == 403


def test_cannot_modify_or_delete_another_companys_safety_procedure(client, auth_headers):
    acme_headers = auth_headers("supervisor", company_id="acme-elevator")
    create_resp = client.post(
        "/companies/acme-elevator/safety-procedures",
        json={"equipment_type": "elevator", "section": "1.1", "text": "Do not enter shaft.", "source_manual": "Manual"},
        headers=acme_headers,
    )
    assert create_resp.status_code == 201
    proc_id = create_resp.json()["id"]

    demo_headers = auth_headers("supervisor", company_id="site-demo")

    # Cannot modify acme safety procedure
    put_resp = client.put(
        f"/companies/acme-elevator/safety-procedures/{proc_id}",
        json={"equipment_type": "elevator", "section": "1.1", "text": "Hacked", "source_manual": "Manual"},
        headers=demo_headers,
    )
    assert put_resp.status_code == 403

    # Cannot delete acme safety procedure
    del_resp = client.delete(
        f"/companies/acme-elevator/safety-procedures/{proc_id}",
        headers=demo_headers,
    )
    assert del_resp.status_code == 403


def test_cannot_issue_call_role_token_or_sync_for_another_company(client, auth_headers):
    demo_headers = auth_headers("supervisor", company_id="site-demo")

    # Cannot issue call role token for acme
    token_resp = client.post("/companies/acme-elevator/call-role-token", headers=demo_headers)
    assert token_resp.status_code == 403

    # Cannot trigger sync for acme
    sync_resp = client.post("/companies/acme-elevator/sync", headers=demo_headers)
    assert sync_resp.status_code == 403

    # Cannot update acme company details
    put_comp_resp = client.put(
        "/companies/acme-elevator",
        json={"name": "Hacked Name"},
        headers=demo_headers,
    )
    assert put_comp_resp.status_code == 403
