import main


def test_sync_rate_limiting_enforcement(client, auth_headers):
    main.limiter.enabled = True
    try:
        headers = auth_headers("supervisor", company_id="site-demo")
        statuses = [
            client.post("/companies/site-demo/sync", headers=headers).status_code
            for _ in range(25)
        ]
        assert 200 in statuses
        assert 429 in statuses
        assert statuses[-1] == 429
    finally:
        main.limiter.enabled = False
