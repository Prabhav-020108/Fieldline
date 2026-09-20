"""
Tests for the offline half of moss_client.py:

  - _LocalSession: the in-memory keyword search the agent uses when there is
    no network (FR-07).
  - MossRouter.add_docs: a note written offline must be searchable
    immediately AND queued for the cloud (FR-06, FR-08, NFR-15).

Nothing here talks to Moss or the backend -- the cloud client is a fake.

    uv run pytest tests/test_moss_client.py -v
"""

import json
from types import SimpleNamespace

import pytest
from moss import DocumentInfo

import sync_queue
from connectivity import connectivity
from moss_client import MossRouter, _LocalSession

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _options(filter_type=None, top_k=5):
    """A stand-in for moss.QueryOptions: _LocalSession only reads .filter and .top_k."""
    flt = None
    if filter_type is not None:
        flt = {"field": "type", "condition": {"$eq": filter_type}}
    return SimpleNamespace(filter=flt, top_k=top_k)


def _sample_docs():
    return [
        DocumentInfo(
            id="job-1",
            text="unit-12 - Tripped overload on the 8th, reset by Anil. Resolution: Breaker reset, monitored 48h.",
            metadata={"type": "job_history", "equipment": "unit-12"},
        ),
        DocumentInfo(
            id="job-2",
            text="unit-12 - Recurring low-refrigerant flag on the 15th. Resolution: open.",
            metadata={"type": "job_history", "equipment": "unit-12"},
        ),
        DocumentInfo(
            id="job-3",
            text="unit-3 - Lockout tag left on the disconnect, removed by Anil. Resolution: tag removed.",
            metadata={"type": "job_history", "equipment": "unit-3"},
        ),
        DocumentInfo(
            id="inventory-1",
            text="Schneider contactor (part LC1D18) - stored at bin 14C, site store room, qty 3.",
            metadata={"type": "inventory", "part_number": "LC1D18"},
        ),
        DocumentInfo(
            id="safety-panel-b-4.2",
            text="Section 4.2 - Panel B Lockout: (1) Notify affected personnel before de-energizing.",
            metadata={"type": "safety_manual", "section": "4.2"},
        ),
    ]


async def _loaded_session() -> _LocalSession:
    session = _LocalSession()
    await session.add_docs(_sample_docs())
    return session


def _ids(results) -> list[str]:
    return [doc.id for doc in results.docs]


# --------------------------------------------------------------------------
# _LocalSession (offline keyword search)
# --------------------------------------------------------------------------


async def test_without_a_filter_every_document_type_is_searched():
    session = await _loaded_session()

    results = await session.query("lockout", _options())

    assert set(_ids(results)) == {"job-3", "safety-panel-b-4.2"}


async def test_the_type_filter_only_returns_that_kind_of_document():
    session = await _loaded_session()

    results = await session.query("lockout", _options("safety_manual"))

    assert _ids(results) == ["safety-panel-b-4.2"]


async def test_documents_matching_more_keywords_rank_first():
    session = await _loaded_session()

    results = await session.query("unit-12 overload", _options("job_history"))

    assert _ids(results) == ["job-1", "job-2"]
    assert results.docs[0].score == pytest.approx(1.0)  # both words found
    assert results.docs[1].score == pytest.approx(0.5)  # only "unit-12" found


async def test_top_k_limits_the_number_of_results():
    session = await _loaded_session()

    results = await session.query("unit-12", _options("job_history", top_k=1))

    assert len(results.docs) == 1


async def test_a_part_number_search_is_case_insensitive():
    session = await _loaded_session()

    results = await session.query("LC1D18", _options("inventory"))

    assert _ids(results) == ["inventory-1"]


async def test_very_short_words_are_ignored_and_no_match_returns_nothing():
    session = await _loaded_session()

    assert (await session.query("is at on", _options())).docs == []  # all words <= 2 letters
    assert (await session.query("zebra", _options())).docs == []  # no document has it


async def test_a_document_added_later_is_searchable_immediately():
    session = await _loaded_session()
    await session.add_docs(
        [
            DocumentInfo(
                id="note-unit-12-abc",
                text="unit-12 - field note logged 2026-09-20 10:00 UTC: replaced the capacitor",
                metadata={"type": "job_history", "equipment": "unit-12"},
            )
        ]
    )

    results = await session.query("capacitor", _options("job_history"))

    assert _ids(results) == ["note-unit-12-abc"]


# --------------------------------------------------------------------------
# MossRouter.add_docs (write path: local first, then cloud or the queue)
# --------------------------------------------------------------------------


class _FakeCloudClient:
    """Stands in for the Moss cloud client. Set fail=True to simulate an outage."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, list]] = []

    async def add_docs(self, index_name, docs, mutation_options=None):
        if self.fail:
            raise RuntimeError("simulated cloud outage")
        self.calls.append((index_name, list(docs)))
        return "ok"


@pytest.fixture(autouse=True)
def _isolated_queue_and_online_state(tmp_path, monkeypatch):
    """Each test gets its own throwaway queue file and starts 'online'."""
    monkeypatch.setattr(sync_queue, "DB_PATH", str(tmp_path / "test_queue.sqlite3"))
    monkeypatch.setattr(connectivity, "is_online", True)


def _make_router(cloud_client) -> MossRouter:
    router = MossRouter("site-demo", "site-demo", cloud_client)
    router._session = _LocalSession()  # skip downloading data from the backend
    return router


def _note_doc() -> DocumentInfo:
    return DocumentInfo(
        id="note-unit-12-abc",
        text="unit-12 - field note logged 2026-09-20 10:00 UTC: replaced the contactor",
        metadata={"type": "job_history", "equipment": "unit-12", "status": "open"},
    )


def _queue_rows() -> list[tuple]:
    conn = sync_queue._get_connection()
    try:
        return conn.execute(
            "SELECT op_type, company_id, payload, idempotency_key FROM sync_queue"
        ).fetchall()
    finally:
        conn.close()


async def test_online_write_reaches_the_cloud_and_the_local_index_without_queueing():
    cloud = _FakeCloudClient()
    router = _make_router(cloud)

    await router.add_docs("site-demo", [_note_doc()], None)

    assert len(cloud.calls) == 1
    assert cloud.calls[0][0] == "site-demo"
    assert _queue_rows() == []
    found = await router.query("site-demo", "contactor", None)
    assert _ids(found) == ["note-unit-12-abc"]


async def test_offline_write_is_searchable_locally_and_queued_for_the_cloud(monkeypatch):
    monkeypatch.setattr(connectivity, "is_online", False)
    cloud = _FakeCloudClient()
    router = _make_router(cloud)

    await router.add_docs("site-demo", [_note_doc()], None)

    assert cloud.calls == []  # no cloud attempt while offline

    found = await router.query("site-demo", "contactor", None)
    assert _ids(found) == ["note-unit-12-abc"]  # visible right away, offline

    rows = _queue_rows()
    assert len(rows) == 1
    op_type, company_id, payload_json, _key = rows[0]
    assert op_type == "moss_add_docs"
    assert company_id == "site-demo"
    payload = json.loads(payload_json)
    assert payload["index_name"] == "site-demo"
    assert [d["id"] for d in payload["docs"]] == ["note-unit-12-abc"]


async def test_a_cloud_failure_queues_the_write_and_flips_to_offline():
    cloud = _FakeCloudClient(fail=True)
    router = _make_router(cloud)

    await router.add_docs("site-demo", [_note_doc()], None)

    assert connectivity.is_online is False  # the failed call marked us offline
    assert len(_queue_rows()) == 1  # ...and the write was not lost
    found = await router.query("site-demo", "contactor", None)
    assert _ids(found) == ["note-unit-12-abc"]


async def test_the_same_offline_write_is_only_queued_once(monkeypatch):
    """NFR-15: the idempotency key stops a repeated write being queued twice."""
    monkeypatch.setattr(connectivity, "is_online", False)
    router = _make_router(_FakeCloudClient())

    await router.add_docs("site-demo", [_note_doc()], None)
    await router.add_docs("site-demo", [_note_doc()], None)

    assert len(_queue_rows()) == 1
