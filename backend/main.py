"""
FieldLine dispatch backend -- FastAPI service behind the Next.js dashboard.

Endpoints, grouped by resource:
  - /auth/token                                 Phase 7: login, issues a JWT
  - /auth/me                                     Phase 7: who am I (for the dashboard sidebar)
  - /companies                                  company CRUD (multi-tenant root)
  - /companies/{id}/jobs                        job CRUD + /reroute
  - /companies/{id}/inventory                   inventory CRUD
  - /companies/{id}/safety-procedures           safety-procedure CRUD
  - /companies/{id}/audit-log                   Phase 6: append-only tool-call log
  - /companies/{id}/export                      everything the agent needs to hydrate
                                                 that company's local offline session
  - /companies/{id}/sync                        force an immediate push to Moss

Phase 7 security additions:
  - JWT auth (backend/auth.py) protects every WRITE endpoint (create/
    update/delete). Reads stay public -- see the module-level note below
    for why, and README.md's Phase 7 section for the full reasoning.
  - Role-based access control: dispatcher-only job reroute; supervisor-or-
    dispatcher-only safety procedure writes; any logged-in role for
    ordinary job/inventory writes.
  - Tenant isolation: a valid token for company A can never be used to
    mutate company B's data (auth.require_same_company).
  - Rate limiting (slowapi) on the login endpoint and every write endpoint.
  - Tightened Pydantic request models with explicit length/pattern/range
    constraints instead of bare `str`/`int`.

SCOPING NOTE: /companies (create/update) and /companies/{id}/audit-log
(POST, written by the agent process) are intentionally left WITHOUT auth.
Company CRUD has no "admin" role yet in this three-role model -- a
reasonable Phase 8+ addition, not rushed in here. The audit-log write is a
machine-to-machine call from the trusted agent process (not the browser);
requiring the agent to manage a rotating JWT for pure telemetry writes is
a real future improvement (a static service credential is the natural next
step) but wasn't worth the risk of breaking Phase 6's working audit trail
this week. Both decisions are called out in docs/REQUIREMENTS_TRACEABILITY.md.

Run this from the backend/ folder, with its virtual environment active:

    python -m uvicorn main:app --reload --port 8000

Then open http://localhost:8000/docs for FastAPI's interactive API explorer.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

import auth
import moss_sync
from document_builder import dispatch_queue_doc, dispatch_reroute_doc, inventory_to_doc, job_to_doc, safety_to_doc
from models import AuditLogEntry, Company, DispatchEvent, InventoryItem, Job, SafetyProcedure, SessionLocal, User

logger = logging.getLogger("fieldline.backend")
logging.basicConfig(level=logging.INFO)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="FieldLine Dispatch Backend")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests -- please slow down and try again shortly."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic schemas (Phase 7: tightened with explicit constraints)
# ---------------------------------------------------------------------------

COMPANY_ID_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$"


class CompanyIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=64, pattern=COMPANY_ID_PATTERN)
    name: str = Field(..., min_length=1, max_length=200)
    industry: str = Field(default="other", max_length=50)
    language_preference: str = Field(default="hinglish", max_length=20)
    moss_index_name: Optional[str] = Field(default=None, max_length=100)


class CompanyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    industry: Optional[str] = Field(default=None, max_length=50)
    language_preference: Optional[str] = Field(default=None, max_length=20)


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    industry: str
    language_preference: str
    moss_index_name: str


class JobIn(BaseModel):
    id: Optional[str] = Field(default=None, max_length=64)
    equipment_id: str = Field(..., min_length=1, max_length=100)
    site_id: str = Field(default="", max_length=100)
    fault_description: str = Field(..., min_length=1, max_length=2000)
    resolution: Optional[str] = Field(default=None, max_length=2000)
    status: str = Field(default="open", pattern=r"^(open|closed)$")


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
    id: Optional[str] = Field(default=None, max_length=64)
    part_number: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    location: str = Field(..., min_length=1, max_length=200)
    quantity: int = Field(default=0, ge=0, le=1_000_000)


class InventoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    company_id: str
    part_number: str
    name: str
    location: str
    quantity: int


class SafetyProcedureIn(BaseModel):
    id: Optional[str] = Field(default=None, max_length=64)
    equipment_type: str = Field(..., min_length=1, max_length=100)
    section: str = Field(..., min_length=1, max_length=20)
    text: str = Field(..., min_length=1, max_length=8000)
    source_manual: str = Field(default="Site Safety Manual", max_length=200)


class SafetyProcedureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    company_id: str
    equipment_type: str
    section: str
    text: str
    source_manual: str


class AuditLogIn(BaseModel):
    tool_name: str = Field(..., max_length=50)
    query_text: str = Field(..., max_length=4000)
    response_text: str = Field(..., max_length=4000)
    source_citation: Optional[str] = Field(default=None, max_length=300)
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    below_confidence_floor: bool = False
    created_at: Optional[str] = Field(default=None, max_length=64)


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    company_id: str
    tool_name: str
    query_text: str
    response_text: str
    source_citation: Optional[str] = None
    confidence_score: Optional[float] = None
    below_confidence_floor: bool
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_company_or_404(db, company_id: str) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"No company '{company_id}'")
    return company


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _background_sync(company_id: str, background_tasks: BackgroundTasks) -> None:
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
# Auth (Phase 7)
# ---------------------------------------------------------------------------

@app.post("/auth/token")
@limiter.limit("20/minute")
def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    """Standard OAuth2 password-flow login. See backend/seed_db.py for
    demo accounts (password FieldLine123! for all of them)."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == form_data.username).first()
        if user is None or not auth.verify_password(form_data.password, user.hashed_password):
            raise HTTPException(
                status_code=401,
                detail="Incorrect username or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = auth.create_access_token(
            username=user.username, role=user.role, company_id=user.company_id
        )
        return {
            "access_token": token,
            "token_type": "bearer",
            "role": user.role,
            "company_id": user.company_id,
        }
    finally:
        db.close()


@app.get("/auth/me")
def read_current_user(user: dict = Depends(auth.get_current_user)):
    return user


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
@limiter.limit("10/minute")
def create_company(request: Request, payload: CompanyIn, background_tasks: BackgroundTasks):
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
@limiter.limit("30/minute")
def update_company(
    request: Request,
    company_id: str,
    payload: CompanyUpdate,
    user: dict = Depends(auth.get_current_user),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("20/minute")
async def sync_company_now(
    request: Request, company_id: str, user: dict = Depends(auth.get_current_user)
):
    auth.require_same_company(user, company_id)
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
    finally:
        db.close()
    count = await moss_sync.sync_company(company_id)
    return {"synced_documents": count}


@app.post("/companies/{company_id}/call-role-token")
@limiter.limit("30/minute")
def issue_call_role_token(
    request: Request, company_id: str, user: dict = Depends(auth.get_current_user)
):
    """Phase 8c: minted right before the dashboard starts a voice call and
    carried as the joining participant's LiveKit metadata. The agent
    verifies it locally, with no network call -- see
    agent/src/role_cache.py -- so the role check still works for the rest
    of the call even if the network drops the instant after this."""
    auth.require_same_company(user, company_id)
    token = auth.create_call_role_token(company_id=company_id, role=user["role"])
    return {"token": token, "role": user["role"]}


@app.get("/companies/{company_id}/export")
def export_company(company_id: str):
    """Called by agent/src/moss_client.py's hydrate_session(). Left
    unauthenticated -- see the module docstring's scoping note."""
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
@limiter.limit("30/minute")
def create_job(
    request: Request,
    company_id: str,
    payload: JobIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.get_current_user),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("30/minute")
def update_job(
    request: Request,
    company_id: str,
    job_id: str,
    payload: JobIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.get_current_user),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("30/minute")
def delete_job(
    request: Request,
    company_id: str,
    job_id: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.require_role("supervisor", "dispatcher")),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("30/minute")
def reroute_job(
    request: Request,
    company_id: str,
    job_id: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.require_role("dispatcher")),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("30/minute")
def create_inventory(
    request: Request,
    company_id: str,
    payload: InventoryIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.get_current_user),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("30/minute")
def update_inventory(
    request: Request,
    company_id: str,
    item_id: str,
    payload: InventoryIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.get_current_user),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("30/minute")
def delete_inventory(
    request: Request,
    company_id: str,
    item_id: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.require_role("supervisor", "dispatcher")),
):
    auth.require_same_company(user, company_id)
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
# Safety procedures (Phase 7g: supervisor/dispatcher only -- matches the
# build plan's explicit example for these endpoints)
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
@limiter.limit("30/minute")
def create_safety_procedure(
    request: Request,
    company_id: str,
    payload: SafetyProcedureIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.require_role("supervisor", "dispatcher")),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("30/minute")
def update_safety_procedure(
    request: Request,
    company_id: str,
    procedure_id: str,
    payload: SafetyProcedureIn,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.require_role("supervisor", "dispatcher")),
):
    auth.require_same_company(user, company_id)
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
@limiter.limit("30/minute")
def delete_safety_procedure(
    request: Request,
    company_id: str,
    procedure_id: str,
    background_tasks: BackgroundTasks,
    user: dict = Depends(auth.require_role("supervisor", "dispatcher")),
):
    auth.require_same_company(user, company_id)
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


# ---------------------------------------------------------------------------
# Audit log (Phase 6; scoping note in the module docstring on why the POST
# below stays unauthenticated)
# ---------------------------------------------------------------------------

@app.post("/companies/{company_id}/audit-log", response_model=AuditLogOut, status_code=201)
def create_audit_log_entry(company_id: str, payload: AuditLogIn):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        entry = AuditLogEntry(
            id=f"audit-{_new_id()}",
            company_id=company_id,
            tool_name=payload.tool_name,
            query_text=payload.query_text,
            response_text=payload.response_text,
            source_citation=payload.source_citation,
            confidence_score=payload.confidence_score,
            below_confidence_floor=payload.below_confidence_floor,
            created_at=payload.created_at or datetime.now(timezone.utc).isoformat(),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
    finally:
        db.close()


@app.get("/companies/{company_id}/audit-log", response_model=list[AuditLogOut])
def list_audit_log(company_id: str, limit: int = 200):
    db = SessionLocal()
    try:
        _get_company_or_404(db, company_id)
        return (
            db.query(AuditLogEntry)
            .filter(AuditLogEntry.company_id == company_id)
            .order_by(AuditLogEntry.created_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()