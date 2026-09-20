"""
Unit tests for document_builder.py -- the functions that turn database rows
into the {"id", "text", "metadata"} documents used by BOTH the Moss cloud
sync and the agent's offline index. No HTTP and no database involved.

    uv run pytest tests/test_document_builder.py -v
"""

from document_builder import (
    dispatch_queue_doc,
    dispatch_reroute_doc,
    inventory_to_doc,
    job_to_doc,
    safety_to_doc,
)
from models import InventoryItem, Job, SafetyProcedure


def _job(job_id="2", equipment="unit-12", fault="Recurring low-refrigerant flag on the 15th",
         resolution=None, status="open", priority=False):
    return Job(
        id=job_id,
        company_id="site-demo",
        equipment_id=equipment,
        site_id="site-demo",
        fault_description=fault,
        resolution=resolution,
        status=status,
        priority=priority,
    )


def test_open_job_document_says_resolution_open():
    doc = job_to_doc(_job())

    assert doc["id"] == "job-2"
    assert doc["text"] == (
        "unit-12 - Recurring low-refrigerant flag on the 15th. Resolution: open."
    )
    assert doc["metadata"] == {
        "type": "job_history",
        "equipment": "unit-12",
        "site": "site-demo",
        "status": "open",
    }


def test_closed_job_document_includes_the_resolution():
    doc = job_to_doc(
        _job(
            job_id="1",
            fault="Tripped overload on the 8th, reset by Anil",
            resolution="Breaker reset, monitored 48h",
            status="closed",
        )
    )
    assert doc["text"] == (
        "unit-12 - Tripped overload on the 8th, reset by Anil. "
        "Resolution: Breaker reset, monitored 48h."
    )
    assert doc["metadata"]["status"] == "closed"


def test_inventory_document():
    item = InventoryItem(
        id="1",
        company_id="site-demo",
        part_number="LC1D18",
        name="Schneider contactor",
        location="bin 14C, site store room",
        quantity=3,
    )
    doc = inventory_to_doc(item)

    assert doc["id"] == "inventory-1"
    assert doc["text"] == (
        "Schneider contactor (part LC1D18) - stored at bin 14C, site store room, qty 3."
    )
    assert doc["metadata"] == {
        "type": "inventory",
        "part_number": "LC1D18",
        "location": "bin 14C, site store room",
    }


def test_safety_document_keeps_the_procedure_text_verbatim():
    text = "Section 4.2 - Panel B Lockout: (1) Notify affected personnel."
    proc = SafetyProcedure(
        id="panel-b-4.2",
        company_id="site-demo",
        equipment_type="panel-b",
        section="4.2",
        text=text,
        source_manual="Site Electrical Safety Manual",
    )
    doc = safety_to_doc(proc)

    assert doc["id"] == "safety-panel-b-4.2"
    assert doc["text"] == text  # never rewritten: the agent reads it back word for word
    assert doc["metadata"] == {
        "type": "safety_manual",
        "equipment_type": "panel-b",
        "source_manual": "Site Electrical Safety Manual",
        "section": "4.2",
    }


def test_dispatch_queue_lists_only_open_jobs():
    closed = _job(job_id="1", fault="Tripped overload", resolution="Reset", status="closed")
    open_job = _job()
    doc = dispatch_queue_doc("site-demo", [closed, open_job])

    assert doc["id"] == "dispatch-queue-site-demo"
    assert doc["text"] == (
        "Current job queue for site-demo: 1 open job(s) -- "
        "unit-12 (Recurring low-refrigerant flag on the 15th)."
    )
    assert doc["metadata"]["status"] == "open"


def test_dispatch_queue_joins_several_open_jobs():
    doc = dispatch_queue_doc(
        "acme-elevator",
        [_job(job_id="a", equipment="lift-3", fault="Governor tripped"),
         _job(job_id="b", equipment="lift-4", fault="Door sensor fault")],
    )
    assert doc["text"] == (
        "Current job queue for acme-elevator: 2 open job(s) -- "
        "lift-3 (Governor tripped); lift-4 (Door sensor fault)."
    )


def test_dispatch_queue_with_no_open_jobs():
    doc = dispatch_queue_doc("acme-elevator", [_job(status="closed", resolution="Done")])

    assert doc["text"] == "Current job queue for acme-elevator: no open jobs. All jobs are closed."
    assert doc["metadata"]["status"] == "closed"


def test_dispatch_reroute_document():
    doc = dispatch_reroute_doc("site-demo", _job(priority=True))

    assert doc["id"] == "dispatch-reroute-2"
    assert "rerouted to priority status" in doc["text"]
    assert "unit-12" in doc["text"]
    assert doc["metadata"] == {
        "type": "dispatch_status",
        "company_id": "site-demo",
        "job_id": "2",
        "event": "reroute",
    }
