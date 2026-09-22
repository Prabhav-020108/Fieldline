"""
Canonical seed data for FieldLine demo environments.
Used by both backend/seed_db.py and Alembic migration versions.
"""

from auth import hash_password

DEMO_PASSWORD = "FieldLine123!"

COMPANIES = [
    {
        "id": "site-demo",
        "name": "Site Demo Electrical Co.",
        "industry": "electrical",
        "language_preference": "hinglish",
        "moss_index_name": "site-demo",
    },
    {
        "id": "acme-elevator",
        "name": "Acme Elevator AMC",
        "industry": "elevator_amc",
        "language_preference": "english",
        "moss_index_name": "company-acme-elevator",
    },
]

JOBS = [
    {
        "id": "1",
        "company_id": "site-demo",
        "equipment_id": "unit-12",
        "site_id": "site-demo",
        "fault_description": "Tripped overload on the 8th, reset by Anil",
        "resolution": "Breaker reset, monitored 48h",
        "status": "closed",
        "priority": False,
    },
    {
        "id": "2",
        "company_id": "site-demo",
        "equipment_id": "unit-12",
        "site_id": "site-demo",
        "fault_description": "Recurring low-refrigerant flag on the 15th",
        "resolution": None,
        "status": "open",
        "priority": False,
    },
    {
        "id": "elev-1",
        "company_id": "acme-elevator",
        "equipment_id": "lift-3",
        "site_id": "tower-a",
        "fault_description": "Door sensor misalignment causing intermittent re-opens",
        "resolution": "Sensor bracket realigned and torqued, tested 20 cycles clean",
        "status": "closed",
        "priority": False,
    },
    {
        "id": "elev-2",
        "company_id": "acme-elevator",
        "equipment_id": "lift-3",
        "site_id": "tower-a",
        "fault_description": "Overspeed governor tripped during routine inspection on the 10th",
        "resolution": None,
        "status": "open",
        "priority": False,
    },
]

INVENTORY = [
    {
        "id": "1",
        "company_id": "site-demo",
        "part_number": "LC1D18",
        "name": "Schneider contactor",
        "location": "bin 14C, site store room",
        "quantity": 3,
    },
    {
        "id": "elev-inv-1",
        "company_id": "acme-elevator",
        "part_number": "GOV-OS-200",
        "name": "Overspeed governor switch assembly",
        "location": "tower-a machine room, shelf 2",
        "quantity": 1,
    },
]

SAFETY_PROCEDURES = [
    {
        "id": "panel-b-4.2",
        "company_id": "site-demo",
        "equipment_type": "panel-b",
        "section": "4.2",
        "text": (
            "Section 4.2 - Panel B Lockout: (1) Notify affected personnel "
            "before de-energizing. (2) Shut down the equipment using the "
            "normal stop procedure. (3) Isolate the energy source at the "
            "disconnect. (4) Apply a lock and a tag identifying who applied "
            "it. (5) Release any stored energy (capacitors, springs, "
            "pressure). (6) Verify a zero-energy state with a meter before "
            "starting work."
        ),
        "source_manual": "Site Electrical Safety Manual",
    },
    {
        "id": "panel-a-4.1",
        "company_id": "site-demo",
        "equipment_type": "panel-a",
        "section": "4.1",
        "text": (
            "Section 4.1 - Panel A Lockout: follows the same six-step "
            "sequence as 4.2, with an additional secondary lock point at "
            "the upstream feeder breaker due to a shared bus with Panel B."
        ),
        "source_manual": "Site Electrical Safety Manual",
    },
    {
        "id": "elev-lockout-3.1",
        "company_id": "acme-elevator",
        "equipment_type": "traction-lift",
        "section": "3.1",
        "text": (
            "Section 3.1 - Traction Lift Lockout: (1) Notify building "
            "management and post an out-of-service sign at every landing. "
            "(2) Recall the car to the machine-room level and open the main "
            "disconnect. (3) Apply lock and tag at the disconnect. (4) "
            "Mechanically block the car with the car-top safety bar before "
            "anyone enters the shaft or pit. (5) Verify zero energy at the "
            "controller with a meter before starting work."
        ),
        "source_manual": "Acme Elevator AMC Safety Manual",
    },
]


def get_seed_users() -> list[dict]:
    pwd_hash = hash_password(DEMO_PASSWORD)
    return [
        {
            "id": "user-site-demo-tech",
            "company_id": "site-demo",
            "username": "tech.demo",
            "hashed_password": pwd_hash,
            "role": "technician",
        },
        {
            "id": "user-site-demo-supervisor",
            "company_id": "site-demo",
            "username": "supervisor.demo",
            "hashed_password": pwd_hash,
            "role": "supervisor",
        },
        {
            "id": "user-site-demo-dispatcher",
            "company_id": "site-demo",
            "username": "dispatcher.demo",
            "hashed_password": pwd_hash,
            "role": "dispatcher",
        },
        {
            "id": "user-acme-tech",
            "company_id": "acme-elevator",
            "username": "tech.acme",
            "hashed_password": pwd_hash,
            "role": "technician",
        },
        {
            "id": "user-acme-supervisor",
            "company_id": "acme-elevator",
            "username": "supervisor.acme",
            "hashed_password": pwd_hash,
            "role": "supervisor",
        },
        {
            "id": "user-acme-dispatcher",
            "company_id": "acme-elevator",
            "username": "dispatcher.acme",
            "hashed_password": pwd_hash,
            "role": "dispatcher",
        },
    ]
