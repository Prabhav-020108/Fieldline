"""
Turns SQLAlchemy rows into the plain {"id", "text", "metadata"} document
shape Moss expects (moss.DocumentInfo has the same three fields).

Used in two places, so the two stay identical instead of drifting apart:
  - moss_sync.py    -> wraps these in DocumentInfo and pushes to the Moss
                        cloud index for a company.
  - main.py's        -> GET /companies/{id}/export returns these same dicts
    export endpoint     as JSON, which agent/src/moss_client.py fetches to
                         hydrate that company's local, offline-capable
                         session at shift start.
"""

from models import InventoryItem, Job, SafetyProcedure


def job_to_doc(job: Job) -> dict:
    return {
        "id": f"job-{job.id}",
        "text": f"{job.equipment_id} - {job.fault_description}. Resolution: {job.resolution or 'open'}.",
        "metadata": {
            "type": "job_history",
            "equipment": job.equipment_id,
            "site": job.site_id,
            "status": job.status,
        },
    }


def inventory_to_doc(item: InventoryItem) -> dict:
    return {
        "id": f"inventory-{item.id}",
        "text": f"{item.name} (part {item.part_number}) - stored at {item.location}, qty {item.quantity}.",
        "metadata": {
            "type": "inventory",
            "part_number": item.part_number,
            "location": item.location,
        },
    }


def safety_to_doc(proc: SafetyProcedure) -> dict:
    return {
        "id": f"safety-{proc.id}",
        "text": proc.text,
        "metadata": {
            "type": "safety_manual",
            "equipment_type": proc.equipment_type,
            "source_manual": proc.source_manual,
            "section": proc.section,
        },
    }


def dispatch_queue_doc(company_id: str, jobs: list[Job]) -> dict:
    """Synthesizes the same kind of "current job queue" summary that used
    to live as a static line in data/seed/dispatch.json -- now generated
    fresh from live DB rows so it's always accurate for this company."""
    open_jobs = [j for j in jobs if j.status == "open"]
    if not open_jobs:
        summary = f"Current job queue for {company_id}: no open jobs. All jobs are closed."
    else:
        parts = [f"{j.equipment_id} ({j.fault_description})" for j in open_jobs]
        summary = (
            f"Current job queue for {company_id}: {len(open_jobs)} open job(s) -- "
            + "; ".join(parts)
            + "."
        )
    return {
        "id": f"dispatch-queue-{company_id}",
        "text": summary,
        "metadata": {
            "type": "dispatch_status",
            "company_id": company_id,
            "status": "open" if open_jobs else "closed",
        },
    }


def dispatch_reroute_doc(company_id: str, job: Job) -> dict:
    return {
        "id": f"dispatch-reroute-{job.id}",
        "text": (
            f"Dispatch reroute: job {job.id} ({job.equipment_id}, {job.fault_description}) "
            "was rerouted to priority status. Treat it as the next job after any work "
            "currently in progress."
        ),
        "metadata": {
            "type": "dispatch_status",
            "company_id": company_id,
            "job_id": job.id,
            "event": "reroute",
        },
    }