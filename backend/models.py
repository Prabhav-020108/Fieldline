"""
SQLAlchemy models for the FieldLine dispatch backend.

Phase 5 change: FieldLine is now multi-tenant. Every table that used to
belong to a single hardcoded "site-demo" site now belongs to a specific
Company, via a company_id foreign key. Safety procedures move from a
static JSON file (Phase 2) into a real table, since a company admin edits
these from the dashboard now, not by hand-editing a file you commit to git.

Phase 6 addition: AuditLogEntry -- one row per tool call the voice agent
makes (fault_history / safety_procedure / inventory_lookup /
dispatch_status / log_job_note), so a supervisor can see exactly what the
agent told a technician and where the answer came from. This is a brand
new table, not a change to an existing one, so it does NOT require
deleting db.sqlite3 -- SQLAlchemy's create_all() below just adds the new
table alongside your existing data the next time the backend starts.

NOTE ON MIGRATING AN EXISTING db.sqlite3 (Phase 5 note, still applies to
the Job/Company/InventoryItem/SafetyProcedure tables):
SQLite does not add new columns to a table just because this file changed.
If you already ran seed_db.py before Phase 5 (so backend/db.sqlite3
already exists with the OLD schema), delete it before re-seeding:

    cd backend
    Remove-Item db.sqlite3 -ErrorAction SilentlyContinue
    python seed_db.py

This only deletes local demo data -- your Moss cloud index is untouched,
and seed_db.py recreates the exact same "site-demo" rows plus a new second
company, so nothing from Phases 1-4 is lost.
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
    # The Moss cloud index this company's data lives in. Kept as its own
    # column (rather than always deriving it as f"company-{id}") so
    # Company #1 can keep using the literal "site-demo" index created back
    # in Phase 2, unchanged.
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
    # Set by the dashboard's "Reroute to priority" action -- see main.py's
    # reroute_job(). Drives the dispatch-reroute document the agent's
    # dispatch_status tool retrieves.
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
    text = Column(Text)  # exact, verbatim procedure text -- read back close to word-for-word by the agent
    source_manual = Column(String, default="Site Safety Manual")


class DispatchEvent(Base):
    __tablename__ = "dispatch_events"
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), index=True, nullable=False)
    job_id = Column(String, ForeignKey("jobs.id"))
    technician_id = Column(String, default="")
    event_type = Column(String)  # delay / reroute / assign
    timestamp = Column(String)


class AuditLogEntry(Base):
    """Phase 6: an append-only record of every tool call the voice agent
    makes. Written by agent/src/audit_log.py right after each of the five
    tools answers a technician (fire-and-forget, so it never adds latency
    to the voice response), and read by the dashboard's "Audit log" tab.

    confidence_score and below_confidence_floor are only ever populated by
    safety_procedure today -- the only tool with a confidence floor. Both
    stay NULL / False for the other four tools.
    """
    __tablename__ = "audit_log_entries"
    id = Column(String, primary_key=True)
    company_id = Column(String, ForeignKey("companies.id"), index=True, nullable=False)
    tool_name = Column(String, index=True)
    query_text = Column(Text)
    response_text = Column(Text)
    source_citation = Column(String, nullable=True)
    confidence_score = Column(Float, nullable=True)
    below_confidence_floor = Column(Boolean, default=False)
    created_at = Column(String, index=True)  # ISO 8601 UTC timestamp


engine = create_engine("sqlite:///./db.sqlite3")
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(engine)