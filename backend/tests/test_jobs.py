"""
Job tests: create / update / delete / reroute, validation, role-based access
control (RBAC), and tenant isolation.

Covers: FR-05 (dispatch reroute), NFR-10 (RBAC) and tenant isolation.

    uv run pytest tests/test_jobs.py -v
"""

from models import DispatchEvent, SessionLocal


def _create_job(client, headers, company_id="site-demo", **overrides):
    """Create a job through the API and return its JSON."""
    payload = {
        "equipment_id": "unit-12",
        "site_id": company_id,
        "fault_description": "Recurring low-refrigerant flag",
    }
    payload.update(overrides)
    response = client.post(f"/companies/{company_id}/jobs", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# Create / list
# --------------------------------------------------------------------------


def test_job_list_starts_empty(client):
    response = client.get("/companies/site-demo/jobs")
    assert response.status_code == 200
    assert response.json() == []


def test_create_job_requires_login(client):
    response = client.post(
        "/companies/site-demo/jobs",
        json={"equipment_id": "unit-12", "fault_description": "Tripped overload"},
    )
    assert response.status_code == 401


def test_a_technician_can_create_a_job_and_it_starts_open_and_not_priority(
    client, auth_headers, sync_calls
):
    job = _create_job(client, auth_headers("technician"))

    assert job["id"]
    assert job["company_id"] == "site-demo"
    assert job["equipment_id"] == "unit-12"
    assert job["status"] == "open"
    assert job["priority"] is False
    assert job["resolution"] is None
    assert sync_calls == ["site-demo"]  # every write schedules a Moss sync

    listed = client.get("/companies/site-demo/jobs").json()
    assert [j["id"] for j in listed] == [job["id"]]


def test_create_job_accepts_a_client_supplied_id(client, auth_headers):
    job = _create_job(client, auth_headers("technician"), id="job-explicit-1")
    assert job["id"] == "job-explicit-1"


def test_create_job_validation_errors_return_422(client, auth_headers):
    headers = auth_headers("technician")
    url = "/companies/site-demo/jobs"

    missing_fault = client.post(url, json={"equipment_id": "unit-12"}, headers=headers)
    assert missing_fault.status_code == 422

    empty_equipment = client.post(
        url, json={"equipment_id": "", "fault_description": "x"}, headers=headers
    )
    assert empty_equipment.status_code == 422

    bad_status = client.post(
        url,
        json={"equipment_id": "unit-12", "fault_description": "x", "status": "pending"},
        headers=headers,
    )
    assert bad_status.status_code == 422


def test_create_job_for_a_company_that_does_not_exist_returns_404(client, auth_headers):
    headers = auth_headers("technician", company_id="ghost-co")
    response = client.post(
        "/companies/ghost-co/jobs",
        json={"equipment_id": "unit-1", "fault_description": "x"},
        headers=headers,
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Tenant isolation
# --------------------------------------------------------------------------


def test_each_company_only_sees_its_own_jobs(client, auth_headers):
    _create_job(client, auth_headers("technician"), equipment_id="unit-12")
    _create_job(
        client,
        auth_headers("technician", company_id="acme-elevator"),
        company_id="acme-elevator",
        equipment_id="lift-3",
    )

    demo_jobs = client.get("/companies/site-demo/jobs").json()
    acme_jobs = client.get("/companies/acme-elevator/jobs").json()

    assert [j["equipment_id"] for j in demo_jobs] == ["unit-12"]
    assert [j["equipment_id"] for j in acme_jobs] == ["lift-3"]


def test_cannot_create_a_job_in_another_companys_account(client, auth_headers):
    response = client.post(
        "/companies/site-demo/jobs",
        json={"equipment_id": "unit-99", "fault_description": "sneaky"},
        headers=auth_headers("dispatcher", company_id="acme-elevator"),
    )
    assert response.status_code == 403
    assert client.get("/companies/site-demo/jobs").json() == []


# --------------------------------------------------------------------------
# Update
# --------------------------------------------------------------------------


def test_update_job_changes_resolution_and_status(client, auth_headers):
    headers = auth_headers("technician")
    job = _create_job(client, headers)

    response = client.put(
        f"/companies/site-demo/jobs/{job['id']}",
        json={
            "equipment_id": "unit-12",
            "site_id": "site-demo",
            "fault_description": "Recurring low-refrigerant flag",
            "resolution": "Refrigerant topped up",
            "status": "closed",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolution"] == "Refrigerant topped up"
    assert body["status"] == "closed"


def test_update_unknown_job_returns_404(client, auth_headers):
    response = client.put(
        "/companies/site-demo/jobs/no-such-job",
        json={"equipment_id": "unit-12", "fault_description": "x"},
        headers=auth_headers("technician"),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Delete (supervisor or dispatcher only)
# --------------------------------------------------------------------------


def test_a_technician_cannot_delete_a_job(client, auth_headers):
    job = _create_job(client, auth_headers("technician"))

    response = client.delete(
        f"/companies/site-demo/jobs/{job['id']}", headers=auth_headers("technician")
    )

    assert response.status_code == 403
    assert len(client.get("/companies/site-demo/jobs").json()) == 1


def test_supervisor_and_dispatcher_can_delete_a_job(client, auth_headers):
    for role in ("supervisor", "dispatcher"):
        job = _create_job(client, auth_headers("technician"))
        response = client.delete(
            f"/companies/site-demo/jobs/{job['id']}", headers=auth_headers(role)
        )
        assert response.status_code == 204, f"{role} should be allowed to delete"

    assert client.get("/companies/site-demo/jobs").json() == []


def test_delete_unknown_job_returns_404(client, auth_headers):
    response = client.delete(
        "/companies/site-demo/jobs/no-such-job", headers=auth_headers("dispatcher")
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Reroute (dispatcher only)
# --------------------------------------------------------------------------


def test_only_a_dispatcher_can_reroute_a_job(client, auth_headers):
    job = _create_job(client, auth_headers("technician"))
    url = f"/companies/site-demo/jobs/{job['id']}/reroute"

    assert client.post(url, headers=auth_headers("technician")).status_code == 403
    assert client.post(url, headers=auth_headers("supervisor")).status_code == 403
    assert client.post(url).status_code == 401  # no login at all

    # Nothing changed while access was being denied.
    still = client.get("/companies/site-demo/jobs").json()[0]
    assert still["priority"] is False


def test_dispatcher_reroute_sets_priority_and_records_a_dispatch_event(
    client, auth_headers, sync_calls
):
    job = _create_job(client, auth_headers("technician"))
    sync_calls.clear()  # ignore the sync from creating the job

    response = client.post(
        f"/companies/site-demo/jobs/{job['id']}/reroute", headers=auth_headers("dispatcher")
    )

    assert response.status_code == 200
    assert response.json()["priority"] is True
    assert client.get("/companies/site-demo/jobs").json()[0]["priority"] is True
    assert sync_calls == ["site-demo"]

    db = SessionLocal()
    try:
        events = [
            (e.event_type, e.company_id)
            for e in db.query(DispatchEvent).filter(DispatchEvent.job_id == job["id"]).all()
        ]
    finally:
        db.close()
    assert events == [("reroute", "site-demo")]


def test_reroute_unknown_job_returns_404(client, auth_headers):
    response = client.post(
        "/companies/site-demo/jobs/no-such-job/reroute", headers=auth_headers("dispatcher")
    )
    assert response.status_code == 404


def test_a_dispatcher_from_another_company_cannot_reroute(client, auth_headers):
    job = _create_job(client, auth_headers("technician"))
    response = client.post(
        f"/companies/site-demo/jobs/{job['id']}/reroute",
        headers=auth_headers("dispatcher", company_id="acme-elevator"),
    )
    assert response.status_code == 403
