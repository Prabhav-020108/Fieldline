"""
Data-connector sync job: pushes each company's current jobs, inventory,
safety procedures, and a freshly generated dispatch-queue summary into
THAT company's own Moss cloud index.

Phase 2 version of this file synced one hardcoded index ("site-demo").
Phase 5 loops over every row in the companies table instead, and pushes
each company's rows to its own Company.moss_index_name -- see the Phase 5
build plan's "one Moss index per company" section for why index-per-tenant
was chosen over one shared, filtered index.

Run it by hand any time you want to force a full re-sync of every company:

    cd backend
    python moss_sync.py

The FastAPI backend (main.py) also calls sync_company() for a single
company in the background right after a dashboard edit, so most of the
time you won't need to run this by hand at all.
"""

import asyncio

from dotenv import load_dotenv
from moss import DocumentInfo, MossClient, MutationOptions

from document_builder import dispatch_queue_doc, inventory_to_doc, job_to_doc, safety_to_doc
from models import Company, InventoryItem, Job, SafetyProcedure, SessionLocal
from settings import settings

load_dotenv()

_client: MossClient | None = None


def _get_client() -> MossClient:
    global _client
    if _client is None:
        _client = MossClient(settings.moss_project_id, settings.moss_project_key)
    return _client


def _doc_dict_to_info(doc: dict) -> DocumentInfo:
    return DocumentInfo(id=doc["id"], text=doc["text"], metadata=doc["metadata"])


async def sync_company(company_id: str) -> int:
    """Push one company's current data into its own Moss index. Returns
    how many documents were sent, so callers can log/display it."""
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.id == company_id).first()
        if company is None:
            raise ValueError(f"No company with id {company_id!r} in the database.")

        jobs = db.query(Job).filter(Job.company_id == company_id).all()
        inventory = db.query(InventoryItem).filter(InventoryItem.company_id == company_id).all()
        safety = db.query(SafetyProcedure).filter(SafetyProcedure.company_id == company_id).all()

        docs = [job_to_doc(j) for j in jobs]
        docs += [inventory_to_doc(i) for i in inventory]
        docs += [safety_to_doc(s) for s in safety]
        docs.append(dispatch_queue_doc(company_id, jobs))

        doc_infos = [_doc_dict_to_info(d) for d in docs]
        if doc_infos:
            client = _get_client()
            await client.add_docs(company.moss_index_name, doc_infos, MutationOptions(upsert=True))

        print(
            f"Synced {len(doc_infos)} documents for company '{company_id}' "
            f"-> index '{company.moss_index_name}'."
        )
        return len(doc_infos)
    finally:
        db.close()


async def sync_all() -> None:
    db = SessionLocal()
    try:
        company_ids = [c.id for c in db.query(Company).all()]
    finally:
        db.close()

    for company_id in company_ids:
        await sync_company(company_id)


if __name__ == "__main__":
    asyncio.run(sync_all())
