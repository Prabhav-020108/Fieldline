"""
Seeds the database with demo data for TWO companies:
  - "site-demo"      -- electrical-maintenance demo data
  - "acme-elevator"  -- elevator AMC multi-tenant demo data

Also creates demo login accounts for technician, supervisor, and dispatcher roles.
Data definitions live in backend/seed_data.py.
Safe to re-run any time -- every row uses db.merge(...).
"""

from models import Company, InventoryItem, Job, SafetyProcedure, SessionLocal, User
from seed_data import COMPANIES, DEMO_PASSWORD, INVENTORY, JOBS, SAFETY_PROCEDURES, get_seed_users


def seed() -> None:
    db = SessionLocal()
    try:
        for c in COMPANIES:
            db.merge(Company(**c))

        for j in JOBS:
            db.merge(Job(**j))

        for item in INVENTORY:
            db.merge(InventoryItem(**item))

        for proc in SAFETY_PROCEDURES:
            db.merge(SafetyProcedure(**proc))

        for user in get_seed_users():
            db.merge(User(**user))

        db.commit()
        print(
            f"Seeded database: {len(COMPANIES)} companies, {len(JOBS)} jobs, "
            f"{len(INVENTORY)} inventory items, {len(SAFETY_PROCEDURES)} safety procedures, "
            f"and 6 demo login accounts (password for all: {DEMO_PASSWORD})."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
