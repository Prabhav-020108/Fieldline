"""
FieldLine dispatch backend -- FastAPI service behind the Phase 5 Next.js
dashboard.

Endpoints, grouped by resource:
  - /companies                                  company CRUD (multi-tenant root)
  - /companies/{id}/jobs                        job CRUD + /reroute
  - /companies/{id}/inventory                   inventory CRUD
  - /companies/{id}/safety-procedures           safety-procedure CRUD
  - /companies/{id}/export                      everything the agent needs
                                                 to hydrate that company's
                                                 local, offline-capable
                                                 session (see
                                                 agent/src/moss_client.py)
  - /companies/{id}/sync                        force an immediate push to
                                                 that company's Moss index

Every write endpoint also fires a background sync to Moss, so a dashboard
edit shows up on the technician's next tool call without waiting on a cron
job or a manual `python moss_sync.py` run.

Run this from the backend/ folder, with its virtual environment active:

    python -m uvicorn main:app --reload --port 8000

Then open http://localhost:8000/docs for FastAPI's interactive API explorer
-- handy for testing an endpoint by hand before the dashboard calls it.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

import moss_sync
from document_builder import dispatch_queue_doc, dispatch_reroute_doc, inventory_to_doc, job_to_doc, safety_to_doc
from models import Company, DispatchEvent, InventoryItem, Job, SafetyProcedure, SessionLocal, init_db

logger = logging.getLogger("fieldline.backend")
logging.basicConfig(level=logging.INFO)

init_db()

app = FastAPI(title="FieldLine Dispatch Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CompanyIn(BaseModel):
    id: str
    name: str
    industry: str = "other"
    language_preference: str = "hinglish"
    moss_index_name: Optional[str] = None


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    language_preference: Optional[str] = None


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    industry: str
    language_preference: str
    moss_index_name: str


class JobIn(BaseModel):
    id: Optional[str] = None
    equipment_id: str
    site_id: str = ""
    fault_description: str
    resolution: Optional[str] = None
    status: str = "open"


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    company_id: str
    equipment_id: str
    site_id: str
    fault_description: str
    resolution: Optional[str] = None
    status: str
    priority: bool


class InventoryIn(BaseModel):
    id: Optional[str] = None
    part_number: str
    name: str
    location: str
    quantity: int = 0


class InventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    company_id: str
    part_number: str
    name: str
    location: str
    quantity: int


class SafetyProcedureIn(BaseModel):
    id: Optional[str] = None
    equipment_type: str
    section: str
    text: str
    source_manual: str = "Site Safety Manual"


class SafetyProcedureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    company_id: str
    equipment_type: str
    section: str
    text: str
    source_manual: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_company_or_404(db, company_id: str) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"No company '{company_id}'")
    return company


def _new_id() -> str:
    """Plain random id -- document_builder.py's job_to_doc/inventory_to_doc/
    safety_to_doc already add their own semantic prefix (job-, inventory-,
    safety-) when building the Moss doc id, so the row id itself stays
    unprefixed to avoid ending up with a doubled id like job-job-a1b2c3d4."""
    return uuid.uuid4().hex[:10]


def _background_sync(company_id: str, background_tasks: BackgroundTasks) -> None:
    """Fire a Moss sync for this company in the background, so dashboard
    writes reach the technician's next tool call without blocking the
    HTTP response the dashboard is waiting on."""

    async def _run() -> None:
        try:
            await moss_sync.sync_company(company_id)
        except Exception:
            logger.exception("background sync failed for company %s", company_id)

    background_tasks.add_task(_run)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

@app.get("/companies", response_model=list[CompanyOut])
def list_companies():
    db = SessionLocal()
    try:
        return db.query(Company).all()
    finally:
        db.close()


@app.post("/companies", response_model=CompanyOut, status_code=201)
def create_company(payload: CompanyIn, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        existing = db.query(Company).filter(Company.id == payload.id).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"Company '{payload.id}' already exists")
        index_name = payload.moss_index_name or f"company-{payload.id}"
        company = Company(
            id=payload.id,
            name=payload.name,
            industry=payload.industry,
            language_preference=payload.language_preference,
            moss_index_name=index_name,
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        _background_sync(company.id, background_tasks)
        return company
    finally:
        db.close()


@app.get("/companies/{company_id}", response_model=CompanyOut)
def get_company(company_id: str):
    db = SessionLocal()
    try:
        return _get_company_or_404(db, company_id)
    finally:
        db.close()


@app.put("/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: str, payload: CompanyUpdate):
    db = SessionLocal()
    try:
        company = _get_company_or_404(db, company_id)
        if payload.name is not None:
            company.name = payload.name
        if payload.industry is not None:
            company.industry = payload.industry
        if payload.language_preference is not None:
            company.language_preference = payload.language_preference
        db.commit()
        db.refresh(company)
        return company
    finally:
        db.close()


@app.post("/companies/{company_id}/sync")
async def sync_company_now(company_id: str):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
    finally:
        db.close()
    count = await moss_sync.sync_company(company_id)
    return {"synced_documents": count}


@app.get("/companies/{company_id}/export")
def export_company(company_id: str):
    """Everything agent/src/moss_client.py's hydrate_session() needs to
    build a local, offline-capable session for this company: jobs,
    inventory, safety procedures, a freshly generated dispatch-queue
    document, and one dispatch-reroute document per job that's been
    rerouted -- all as plain {"id", "text", "metadata"} dicts."""
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        jobs = db.query(Job).filter(Job.company_id == company_id).all()
        inventory = db.query(InventoryItem).filter(InventoryItem.company_id == company_id).all()
        safety = db.query(SafetyProcedure).filter(SafetyProcedure.company_id == company_id).all()

        docs = [job_to_doc(j) for j in jobs]
        docs += [inventory_to_doc(i) for i in inventory]
        docs += [safety_to_doc(s) for s in safety]
        docs.append(dispatch_queue_doc(company_id, jobs))

        for job in jobs:
            if job.priority:
                docs.append(dispatch_reroute_doc(company_id, job))

        return {"documents": docs}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.get("/companies/{company_id}/jobs", response_model=list[JobOut])
def list_jobs(company_id: str):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        return db.query(Job).filter(Job.company_id == company_id).all()
    finally:
        db.close()


@app.post("/companies/{company_id}/jobs", response_model=JobOut, status_code=201)
def create_job(company_id: str, payload: JobIn, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        job = Job(
            id=payload.id or _new_id(),
            company_id=company_id,
            equipment_id=payload.equipment_id,
            site_id=payload.site_id,
            fault_description=payload.fault_description,
            resolution=payload.resolution,
            status=payload.status,
            priority=False,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        _background_sync(company_id, background_tasks)
        return job
    finally:
        db.close()


@app.put("/companies/{company_id}/jobs/{job_id}", response_model=JobOut)
def update_job(company_id: str, job_id: str, payload: JobIn, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.company_id == company_id, Job.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job.equipment_id = payload.equipment_id
        job.site_id = payload.site_id
        job.fault_description = payload.fault_description
        job.resolution = payload.resolution
        job.status = payload.status
        db.commit()
        db.refresh(job)
        _background_sync(company_id, background_tasks)
        return job
    finally:
        db.close()


@app.delete("/companies/{company_id}/jobs/{job_id}", status_code=204)
def delete_job(company_id: str, job_id: str, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.company_id == company_id, Job.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        db.delete(job)
        db.commit()
        _background_sync(company_id, background_tasks)
    finally:
        db.close()
    return None


@app.post("/companies/{company_id}/jobs/{job_id}/reroute", response_model=JobOut)
def reroute_job(company_id: str, job_id: str, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.company_id == company_id, Job.id == job_id).first()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        job.priority = True
        event = DispatchEvent(
            id=f"dispatch-{_new_id()}",
            company_id=company_id,
            job_id=job.id,
            technician_id="",
            event_type="reroute",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        db.add(event)
        db.commit()
        db.refresh(job)
        _background_sync(company_id, background_tasks)
        return job
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

@app.get("/companies/{company_id}/inventory", response_model=list[InventoryOut])
def list_inventory(company_id: str):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        return db.query(InventoryItem).filter(InventoryItem.company_id == company_id).all()
    finally:
        db.close()


@app.post("/companies/{company_id}/inventory", response_model=InventoryOut, status_code=201)
def create_inventory(company_id: str, payload: InventoryIn, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        item = InventoryItem(
            id=payload.id or _new_id(),
            company_id=company_id,
            part_number=payload.part_number,
            name=payload.name,
            location=payload.location,
            quantity=payload.quantity,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        _background_sync(company_id, background_tasks)
        return item
    finally:
        db.close()


@app.put("/companies/{company_id}/inventory/{item_id}", response_model=InventoryOut)
def update_inventory(company_id: str, item_id: str, payload: InventoryIn, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        item = (
            db.query(InventoryItem)
            .filter(InventoryItem.company_id == company_id, InventoryItem.id == item_id)
            .first()
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        item.part_number = payload.part_number
        item.name = payload.name
        item.location = payload.location
        item.quantity = payload.quantity
        db.commit()
        db.refresh(item)
        _background_sync(company_id, background_tasks)
        return item
    finally:
        db.close()


@app.delete("/companies/{company_id}/inventory/{item_id}", status_code=204)
def delete_inventory(company_id: str, item_id: str, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        item = (
            db.query(InventoryItem)
            .filter(InventoryItem.company_id == company_id, InventoryItem.id == item_id)
            .first()
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Inventory item not found")
        db.delete(item)
        db.commit()
        _background_sync(company_id, background_tasks)
    finally:
        db.close()
    return None


# ---------------------------------------------------------------------------
# Safety procedures
# ---------------------------------------------------------------------------

@app.get("/companies/{company_id}/safety-procedures", response_model=list[SafetyProcedureOut])
def list_safety_procedures(company_id: str):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        return db.query(SafetyProcedure).filter(SafetyProcedure.company_id == company_id).all()
    finally:
        db.close()


@app.post("/companies/{company_id}/safety-procedures", response_model=SafetyProcedureOut, status_code=201)
def create_safety_procedure(company_id: str, payload: SafetyProcedureIn, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        proc = SafetyProcedure(
            id=payload.id or _new_id(),
            company_id=company_id,
            equipment_type=payload.equipment_type,
            section=payload.section,
            text=payload.text,
            source_manual=payload.source_manual,
        )
        db.add(proc)
        db.commit()
        db.refresh(proc)
        _background_sync(company_id, background_tasks)
        return proc
    finally:
        db.close()


@app.put("/companies/{company_id}/safety-procedures/{procedure_id}", response_model=SafetyProcedureOut)
def update_safety_procedure(
    company_id: str, procedure_id: str, payload: SafetyProcedureIn, background_tasks: BackgroundTasks
):
    db = SessionLocal()
    try:
        proc = (
            db.query(SafetyProcedure)
            .filter(SafetyProcedure.company_id == company_id, SafetyProcedure.id == procedure_id)
            .first()
        )
        if proc is None:
            raise HTTPException(status_code=404, detail="Safety procedure not found")
        proc.equipment_type = payload.equipment_type
        proc.section = payload.section
        proc.text = payload.text
        proc.source_manual = payload.source_manual
        db.commit()
        db.refresh(proc)
        _background_sync(company_id, background_tasks)
        return proc
    finally:
        db.close()


@app.delete("/companies/{company_id}/safety-procedures/{procedure_id}", status_code=204)
def delete_safety_procedure(company_id: str, procedure_id: str, background_tasks: BackgroundTasks):
    db = SessionLocal()
    try:
        proc = (
            db.query(SafetyProcedure)
            .filter(SafetyProcedure.company_id == company_id, SafetyProcedure.id == procedure_id)
            .first()
        )
        if proc is None:
            raise HTTPException(status_code=404, detail="Safety procedure not found")
        db.delete(proc)
        db.commit()
        _background_sync(company_id, background_tasks)
    finally:
        db.close()
    return None