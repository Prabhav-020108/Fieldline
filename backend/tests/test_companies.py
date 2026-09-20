"""
Company tests: create / read / update, validation, tenant isolation, and the
manual "Sync to Moss" endpoint.

    uv run pytest tests/test_companies.py -v
"""


def test_list_companies_returns_the_two_seeded_demo_companies(client):
    response = client.get("/companies")
    assert response.status_code == 200
    assert {c["id"] for c in response.json()} == {"site-demo", "acme-elevator"}


def test_create_then_get_company_and_a_moss_sync_is_scheduled(client, sync_calls):
    payload = {
        "id": "new-co",
        "name": "New Co",
        "industry": "hvac",
        "language_preference": "english",
    }
    created = client.post("/companies", json=payload)

    assert created.status_code == 201
    body = created.json()
    assert body["id"] == "new-co"
    assert body["name"] == "New Co"
    # Default Moss index name is derived from the company id.
    assert body["moss_index_name"] == "company-new-co"

    fetched = client.get("/companies/new-co")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "New Co"

    # Creating a company kicks off a background sync for that company.
    assert sync_calls == ["new-co"]


def test_create_company_respects_a_custom_moss_index_name(client):
    response = client.post(
        "/companies",
        json={"id": "custom-idx", "name": "Custom", "moss_index_name": "my-own-index"},
    )
    assert response.status_code == 201
    assert response.json()["moss_index_name"] == "my-own-index"


def test_create_company_with_a_duplicate_id_returns_409(client):
    response = client.post("/companies", json={"id": "site-demo", "name": "Imposter"})
    assert response.status_code == 409


def test_create_company_with_an_invalid_id_returns_422(client):
    # Uppercase letters, spaces and "!" are all rejected by the id pattern.
    response = client.post("/companies", json={"id": "Not Valid!", "name": "Bad"})
    assert response.status_code == 422


def test_create_company_with_an_empty_name_returns_422(client):
    response = client.post("/companies", json={"id": "empty-name", "name": ""})
    assert response.status_code == 422


def test_get_unknown_company_returns_404(client):
    response = client.get("/companies/does-not-exist")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_update_company_requires_login(client):
    response = client.put("/companies/site-demo", json={"name": "Renamed"})
    assert response.status_code == 401


def test_update_company_changes_only_the_fields_that_were_sent(client, auth_headers):
    response = client.put(
        "/companies/site-demo",
        json={"name": "Renamed Electrical Co."},
        headers=auth_headers("dispatcher"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Electrical Co."
    # industry / language were not sent, so they keep their seeded values.
    assert body["industry"] == "electrical"
    assert body["language_preference"] == "hinglish"


def test_update_company_with_an_empty_name_returns_422(client, auth_headers):
    response = client.put(
        "/companies/site-demo", json={"name": ""}, headers=auth_headers("dispatcher")
    )
    assert response.status_code == 422


def test_update_other_companys_profile_is_forbidden(client, auth_headers):
    """Tenant isolation: an acme token cannot edit site-demo."""
    response = client.put(
        "/companies/site-demo",
        json={"name": "Hijacked"},
        headers=auth_headers("dispatcher", company_id="acme-elevator"),
    )
    assert response.status_code == 403
    assert client.get("/companies/site-demo").json()["name"] == "Site Demo Electrical Co."


def test_manual_sync_requires_login(client):
    assert client.post("/companies/site-demo/sync").status_code == 401


def test_manual_sync_returns_the_document_count_and_syncs_that_company(
    client, auth_headers, sync_calls
):
    response = client.post("/companies/site-demo/sync", headers=auth_headers("technician"))

    assert response.status_code == 200
    assert response.json() == {"synced_documents": 7}  # the fake sync returns 7
    assert sync_calls == ["site-demo"]


def test_manual_sync_of_another_company_is_forbidden(client, auth_headers, sync_calls):
    response = client.post(
        "/companies/site-demo/sync",
        headers=auth_headers("dispatcher", company_id="acme-elevator"),
    )
    assert response.status_code == 403
    assert sync_calls == []
