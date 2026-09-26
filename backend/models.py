"""
SQLAlchemy models for the FieldLine dispatch backend.

Phase 5: multi-tenancy via company_id on every table.
Phase 6: AuditLogEntry -- append-only record of every tool call.
Phase 7: User -- login accounts for the dashboard's JWT auth + RBAC (see
backend/auth.py). Brand new table, so no need to delete db.sqlite3;
SQLAlchemy's create_all() just adds it alongside your existing data.

Phase 8a: the engine now points at Postgres (Supabase), read from
settings.database_url. Schema changes from here on are Alembic
migrations under backend/migrations/ -- never delete a database and
re-run seed_db.py to "fix" a schema mismatch again; run
`alembic revision --autogenerate -m "..."` then `alembic upgrade head`.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from settings import settings

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
    # Phase 11: set server-side on receipt so the dashboard can detect entries
    # synced from offline (where created_at << received_at).
    received_at = Column(String, nullable=True)


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


# pool_pre_ping checks a pooled connection is still alive before handing
# it to a request -- worth having once the database is a network hop
# away (Supabase) rather than a local file.
#
# Edge / test mode: if DATABASE_URL points at SQLite, pass
# check_same_thread=False so FastAPI's thread-pool workers can share the
# same connection without a "created in a thread" crash.
_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
SessionLocal = sessionmaker(bind=engine)



def init_db():
    """Not called automatically anywhere anymore -- Alembic
    (backend/migrations/) is the source of truth for schema now, and
    running this against a database Alembic also manages will conflict
    with it. Kept only as a convenience for a throwaway local SQLite
    database outside the normal Postgres + Alembic flow."""
    Base.metadata.create_all(engine)
    # Phase 11: gracefully add received_at to existing audit_log_entries
    # tables that were created before this column existed (both SQLite and Postgres/Render).
    try:
        with engine.connect() as conn:
            if _is_sqlite:
                conn.execute(text(
                    "ALTER TABLE audit_log_entries ADD COLUMN received_at TEXT"
                ))
            else:
                conn.execute(text(
                    "ALTER TABLE audit_log_entries ADD COLUMN IF NOT EXISTS received_at TEXT"
                ))
            conn.commit()
    except Exception:
        pass  # column already exists -- exactly what we want
