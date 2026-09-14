"""
Seeds backend/db.sqlite3 with demo data for TWO companies:

  - "site-demo"      -- the original electrical-maintenance demo data from
                         Phases 1-4, kept exactly the same content-wise so
                         your primary, most-rehearsed demo path doesn't
                         change at all.
  - "acme-elevator"  -- a small, differently-industried second company
                         (elevator AMC), added in Phase 5 purely to prove
                         the multi-tenant architecture live: same agent
                         code, same five tools, a completely different
                         dataset, zero cross-contamination.

Phase 5 changed the schema (added Company and SafetyProcedure tables, a
company_id column, and a priority flag on Job). SQLite will NOT add those
new columns to an existing db.sqlite3 on its own -- if you already have one
from before Phase 5, delete it first:

    cd backend
    Remove-Item db.sqlite3 -ErrorAction SilentlyContinue
    python seed_db.py

Safe to re-run any time after that -- every row uses db.merge(...), so
re-running this script just re-applies the same seed data instead of
duplicating rows.
"""

from models import Company, InventoryItem, Job, SafetyProcedure, SessionLocal, init_db

init_db()
db = SessionLocal()

# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

companies = [
    Company(
        id="site-demo",
        name="Site Demo Electrical Co.",
        industry="electrical",
        language_preference="hinglish",
        moss_index_name="site-demo",  # the exact index created back in Phase 2 -- unchanged
    ),
    Company(
        id="acme-elevator",
        name="Acme Elevator AMC",
        industry="elevator_amc",
        language_preference="english",
        moss_index_name="company-acme-elevator",
    ),
]
for company in companies:
    db.merge(company)

# ---------------------------------------------------------------------------
# site-demo -- unchanged from Phases 1-4
# ---------------------------------------------------------------------------

jobs = [
    Job(
        id="1",
        company_id="site-demo",
        equipment_id="unit-12",
        site_id="site-demo",
        fault_description="Tripped overload on the 8th, reset by Anil",
        resolution="Breaker reset, monitored 48h",
        status="closed",
        priority=False,
    ),
    Job(
        id="2",
        company_id="site-demo",
        equipment_id="unit-12",
        site_id="site-demo",
        fault_description="Recurring low-refrigerant flag on the 15th",
        resolution=None,
        status="open",
        priority=False,
    ),
]
for job in jobs:
    db.merge(job)

inventory = [
    InventoryItem(
        id="1",
        company_id="site-demo",
        part_number="LC1D18",
        name="Schneider contactor",
        location="bin 14C, site store room",
        quantity=3,
    ),
]
for item in inventory:
    db.merge(item)

safety_procedures = [
    SafetyProcedure(
        id="panel-b-4.2",
        company_id="site-demo",
        equipment_type="panel-b",
        section="4.2",
        text=(
            "Section 4.2 - Panel B Lockout: (1) Notify affected personnel "
            "before de-energizing. (2) Shut down the equipment using the "
            "normal stop procedure. (3) Isolate the energy source at the "
            "disconnect. (4) Apply a lock and a tag identifying who applied "
            "it. (5) Release any stored energy (capacitors, springs, "
            "pressure). (6) Verify a zero-energy state with a meter before "
            "starting work."
        ),
        source_manual="Site Electrical Safety Manual",
    ),
    SafetyProcedure(
        id="panel-a-4.1",
        company_id="site-demo",
        equipment_type="panel-a",
        section="4.1",
        text=(
            "Section 4.1 - Panel A Lockout: follows the same six-step "
            "sequence as 4.2, with an additional secondary lock point at "
            "the upstream feeder breaker due to a shared bus with Panel B."
        ),
        source_manual="Site Electrical Safety Manual",
    ),
]
for proc in safety_procedures:
    db.merge(proc)

# ---------------------------------------------------------------------------
# acme-elevator -- new second company, added in Phase 5
# ---------------------------------------------------------------------------

elevator_jobs = [
    Job(
        id="elev-1",
        company_id="acme-elevator",
        equipment_id="lift-3",
        site_id="tower-a",
        fault_description="Door sensor misalignment causing intermittent re-opens",
        resolution="Sensor bracket realigned and torqued, tested 20 cycles clean",
        status="closed",
        priority=False,
    ),
    Job(
        id="elev-2",
        company_id="acme-elevator",
        equipment_id="lift-3",
        site_id="tower-a",
        fault_description="Overspeed governor tripped during routine inspection on the 10th",
        resolution=None,
        status="open",
        priority=False,
    ),
]
for job in elevator_jobs:
    db.merge(job)

elevator_inventory = [
    InventoryItem(
        id="elev-inv-1",
        company_id="acme-elevator",
        part_number="GOV-OS-200",
        name="Overspeed governor switch assembly",
        location="tower-a machine room, shelf 2",
        quantity=1,
    ),
]
for item in elevator_inventory:
    db.merge(item)

elevator_safety = [
    SafetyProcedure(
        id="elev-lockout-3.1",
        company_id="acme-elevator",
        equipment_type="traction-lift",
        section="3.1",
        text=(
            "Section 3.1 - Traction Lift Lockout: (1) Notify building "
            "management and post an out-of-service sign at every landing. "
            "(2) Recall the car to the machine-room level and open the main "
            "disconnect. (3) Apply lock and tag at the disconnect. (4) "
            "Mechanically block the car with the car-top safety bar before "
            "anyone enters the shaft or pit. (5) Verify zero energy at the "
            "controller with a meter before starting work."
        ),
        source_manual="Acme Elevator AMC Safety Manual",
    ),
]
for proc in elevator_safety:
    db.merge(proc)

db.commit()
db.close()
print("Seeded db.sqlite3: 2 companies, jobs, inventory, and safety procedures.")