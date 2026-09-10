import os
import asyncio
from dotenv import load_dotenv
from moss import MossClient, DocumentInfo, MutationOptions
from models import SessionLocal, Job, InventoryItem

load_dotenv()
client = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
INDEX_NAME = "site-demo"

def job_to_document(job: Job) -> DocumentInfo:
    return DocumentInfo(
        id=f"job-{job.id}",
        text=f"{job.equipment_id} — {job.fault_description}. Resolution: {job.resolution or 'open'}.",
        metadata={"type": "job_history", "equipment": job.equipment_id, "site": job.site_id, "status": job.status},
    )

def inventory_to_document(item: InventoryItem) -> DocumentInfo:
    return DocumentInfo(
        id=f"inventory-{item.id}",
        text=f"{item.name} (part {item.part_number}) — stored at {item.location}, qty {item.quantity}.",
        metadata={"type": "inventory", "part_number": item.part_number, "location": item.location},
    )

async def sync_all():
    db = SessionLocal()
    try:
        job_docs = [job_to_document(j) for j in db.query(Job).all()]
        inv_docs = [inventory_to_document(i) for i in db.query(InventoryItem).all()]
        if job_docs:
            await client.add_docs(INDEX_NAME, job_docs, MutationOptions(upsert=True))
        if inv_docs:
            await client.add_docs(INDEX_NAME, inv_docs, MutationOptions(upsert=True))
        print(f"Synced {len(job_docs)} jobs and {len(inv_docs)} inventory items.")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(sync_all())