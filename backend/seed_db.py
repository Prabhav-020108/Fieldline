from models import init_db, SessionLocal, Job, InventoryItem

init_db()
db = SessionLocal()
jobs = [
    Job(id="1", equipment_id="unit-12", site_id="site-demo",
        fault_description="Tripped overload on the 8th, reset by Anil",
        resolution="Breaker reset, monitored 48h", status="closed"),
    Job(id="2", equipment_id="unit-12", site_id="site-demo",
        fault_description="Recurring low-refrigerant flag on the 15th",
        resolution=None, status="open"),
]
for job in jobs:
    db.merge(job)

inventory = [
    InventoryItem(id="1", part_number="LC1D18", name="Schneider contactor",
                  location="bin 14C, site store room", quantity=3),
]
for item in inventory:
    db.merge(item)

db.commit()
db.close()
print("Seeded db.sqlite3 with demo rows.")