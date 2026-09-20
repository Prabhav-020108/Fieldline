"""
Tests for two endpoints the VOICE AGENT talks to:

  - POST/GET /companies/{id}/audit-log  (agent writes, dashboard reads)
  - GET /companies/{id}/export          (agent downloads it at call start to
                                         build its offline local index)

Covers: FR-05 (a reroute reaches the agent's data), FR-07/FR-08 (the offline
index is built from this export), and the Phase 6 audit trail.

    uv run pytest tests/test_audit_and_export.py -v
"""


def _entry(**overrides):
    entry = {
        "tool_name": "fault_history",
        "query_text": "unit-12",
        "response_text": "Job history for unit-12: ...",
    }
    entry.update(overrides)
    return entry


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------


def test_post_audit_entry_stores_and_returns_it(client):
    response = client.post(
        "/companies/site-demo/audit-log",
        json=_entry(
            tool_name="safety_procedure",
            query_text="panel B lockout",
            response_text="Section 4.2 ...",
            source_citation="Site Electrical Safety Manual, Section 4.2",
            confidence_score=0.82,
            below_confidence_floor=False,
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("audit-")
    assert body["company_id"] == "site-demo"
    assert body["tool_name"] == "safety_procedure"
    assert body["source_citation"] == "Site Electrical Safety Manual, Section 4.2"
    assert body["confidence_score"] == 0.82
    assert body["below_confidence_floor"] is False
    assert body["created_at"]  # filled in automatically when the agent omits it


def test_post_audit_entry_keeps_a_client_supplied_timestamp(client):
    """Offline-buffered entries are replayed later with their ORIGINAL time."""
    stamp = "2026-09-20T10:15:00+00:00"
    response = client.post("/companies/site-demo/audit-log", json=_entry(created_at=stamp))
    assert response.json()["created_at"] == stamp


def test_post_audit_entry_for_unknown_company_returns_404(client):
    response = client.post("/companies/no-such-co/audit-log", json=_entry())
    assert response.status_code == 404


def test_audit_validation_errors_return_422(client):
    url = "/companies/site-demo/audit-log"
    assert client.post(url, json=_entry(confidence_score=1.5)).status_code == 422
    assert client.post(url, json=_entry(confidence_score=-0.1)).status_code == 422
    assert client.post(url, json=_entry(tool_name="x" * 51)).status_code == 422
    assert client.post(url, json={"tool_name": "fault_history"}).status_code == 422


def test_audit_log_lists_newest_first_and_respects_limit(client):
    for stamp in (
        "2026-09-20T09:00:00+00:00",
        "2026-09-20T11:00:00+00:00",
        "2026-09-20T10:00:00+00:00",
    ):
        client.post("/companies/site-demo/audit-log", json=_entry(created_at=stamp))

    everything = client.get("/companies/site-demo/audit-log").json()
    assert [e["created_at"] for e in everything] == [
        "2026-09-20T11:00:00+00:00",
        "2026-09-20T10:00:00+00:00",
        "2026-09-20T09:00:00+00:00",
    ]

    limited = client.get("/companies/site-demo/audit-log?limit=2").json()
    assert [e["created_at"] for e in limited] == [
        "2026-09-20T11:00:00+00:00",
        "2026-09-20T10:00:00+00:00",
    ]


def test_audit_log_is_scoped_per_company(client):
    client.post("/companies/site-demo/audit-log", json=_entry(query_text="demo question"))
    client.post("/companies/acme-elevator/audit-log", json=_entry(query_text="acme question"))

    demo = client.get("/companies/site-demo/audit-log").json()
    acme = client.get("/companies/acme-elevator/audit-log").json()

    assert [e["query_text"] for e in demo] == ["demo question"]
    assert [e["query_text"] for e in acme] == ["acme question"]


def test_audit_log_for_unknown_company_returns_404(client):
    assert client.get("/companies/no-such-co/audit-log").status_code == 404


# --------------------------------------------------------------------------
# Export (what the agent downloads to build its offline index)
# --------------------------------------------------------------------------


def test_export_of_an_empty_company_contains_only_the_queue_summary(client):
    response = client.get("/companies/site-demo/export")

    assert response.status_code == 200
    docs = response.json()["documents"]
    assert [d["id"] for d in docs] == ["dispatch-queue-site-demo"]
    assert "no open jobs" in docs[0]["text"]


def test_export_contains_every_document_type_the_agent_needs(client, auth_headers):
    headers = auth_headers("dispatcher")
    job = client.post(
        "/companies/site-demo/jobs",
        json={
            "equipment_id": "unit-12",
            "site_id": "site-demo",
            "fault_description": "Recurring low-refrigerant flag on the 15th",
        },
        headers=headers,
    ).json()
    item = client.post(
        "/companies/site-demo/inventory",
        json={
            "part_number": "LC1D18",
            "name": "Schneider contactor",
            "location": "bin 14C, site store room",
            "quantity": 3,
        },
        headers=headers,
    ).json()
    proc = client.post(
        "/companies/site-demo/safety-procedures",
        json={
            "equipment_type": "panel-b",
            "section": "4.2",
            "text": "Section 4.2 - Panel B Lockout: (1) Notify affected personnel.",
            "source_manual": "Site Electrical Safety Manual",
        },
        headers=headers,
    ).json()

    docs = client.get("/companies/site-demo/export").json()["documents"]
    by_id = {d["id"]: d for d in docs}

    assert set(by_id) == {
        f"job-{job['id']}",
        f"inventory-{item['id']}",
        f"safety-{proc['id']}",
        "dispatch-queue-site-demo",
    }
    # Every document has exactly the shape the agent's Moss code expects.
    for doc in docs:
        assert set(doc) == {"id", "text", "metadata"}

    assert by_id[f"job-{job['id']}"]["metadata"]["type"] == "job_history"
    assert by_id[f"inventory-{item['id']}"]["metadata"]["type"] == "inventory"
    assert by_id[f"safety-{proc['id']}"]["metadata"]["type"] == "safety_manual"
    assert by_id[f"safety-{proc['id']}"]["text"].startswith("Section 4.2")
    assert "unit-12" in by_id["dispatch-queue-site-demo"]["text"]


def test_a_reroute_appears_in_the_export_as_a_dispatch_document(client, auth_headers):
    """FR-05: dashboard reroute -> backend -> agent's next dispatch_status call."""
    job = client.post(
        "/companies/site-demo/jobs",
        json={"equipment_id": "unit-12", "fault_description": "Low refrigerant"},
        headers=auth_headers("technician"),
    ).json()

    before = client.get("/companies/site-demo/export").json()["documents"]
    assert f"dispatch-reroute-{job['id']}" not in {d["id"] for d in before}

    client.post(
        f"/companies/site-demo/jobs/{job['id']}/reroute", headers=auth_headers("dispatcher")
    )

    after = client.get("/companies/site-demo/export").json()["documents"]
    reroute = next(d for d in after if d["id"] == f"dispatch-reroute-{job['id']}")
    assert reroute["metadata"]["event"] == "reroute"
    assert "rerouted to priority" in reroute["text"]


def test_export_never_mixes_companies(client, auth_headers):
    client.post(
        "/companies/site-demo/jobs",
        json={"equipment_id": "unit-12", "fault_description": "demo fault"},
        headers=auth_headers("technician"),
    )
    client.post(
        "/companies/acme-elevator/jobs",
        json={"equipment_id": "lift-3", "fault_description": "acme fault"},
        headers=auth_headers("technician", company_id="acme-elevator"),
    )

    demo_text = " ".join(
        d["text"] for d in client.get("/companies/site-demo/export").json()["documents"]
    )
    acme_text = " ".join(
        d["text"] for d in client.get("/companies/acme-elevator/export").json()["documents"]
    )

    assert "unit-12" in demo_text and "lift-3" not in demo_text
    assert "lift-3" in acme_text and "unit-12" not in acme_text


def test_export_for_unknown_company_returns_404(client):
    assert client.get("/companies/no-such-co/export").status_code == 404
