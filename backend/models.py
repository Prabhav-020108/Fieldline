"""
SQLAlchemy models for the FieldLine dispatch backend.

Phase 5: multi-tenancy via company_id on every table.
Phase 6: AuditLogEntry -- append-only record of every tool call.
Phase 7: User -- login accounts for the dashboard's JWT auth + RBAC (see
backend/auth.py). Brand new table, so no need to delete db.sqlite3;
SQLAlchemy's create_all() just adds it alongside your existing data.

NOTE ON MIGRATING AN EXISTING db.sqlite3 (only relevant if you're changing
an EXISTING column, not adding a new table): SQLite does not add new
columns to a table just because this file changed. If that ever happens,
delete db.sqlite3 and re-run seed_db.py -- your Moss cloud index is
untouched either way.
"""

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    industry = Column(String, default="other")
    language_preference = Column(String, default="hinglish")
    moss_index_name = Column(String, nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), index=True, nullable=False)
    equipment_id = Column(String, index=True)
    site_id = Column(String, index=True)
    fault_description = Column(String)
    resolution = Column(String, nullable=True)
    status = Column(String, default="open")
    priority = Column(Boolean, default=False)


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), index=True, nullable=False)
    part_number = Column(String, index=True)
    name = Column(String)
    location = Column(String)
    quantity = Column(Integer, default=0)


class SafetyProcedure(Base):
    __tablename__ = "safety_procedures"
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), index=True, nullable=False)
    equipment_type = Column(String)
    section = Column(String)
    text = Column(Text)
    source_manual = Column(String, default="Site Safety Manual")


class DispatchEvent(Base):
    __tablename__ = "dispatch_events"
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), index=True, nullable=False)
    job_id = Column(String, ForeignKey("jobs.id"))
    technician_id = Column(String, default="")
    event_type = Column(String)
    timestamp = Column(String)


class AuditLogEntry(Base):
    __tablename__ = "audit_log_entries"
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), index=True, nullable=False)
    tool_name = Column(String, index=True)
    query_text = Column(Text)
    response_text = Column(Text)
    source_citation = Column(String, nullable=True)
    confidence_score = Column(Float, nullable=True)
    below_confidence_floor = Column(Boolean, default=False)
    created_at = Column(String, index=True)


class User(Base):
    """Phase 7: dashboard login accounts. Provisioned by seed_db.py, not
    through a public self-registration endpoint -- FieldLine is an
    internal ops tool with admin-provisioned accounts, not a public
    service. role is one of "technician" / "supervisor" / "dispatcher";
    see backend/auth.py for what each role can do."""
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="technician")


engine = create_engine("sqlite:///./db.sqlite3")
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(engine)