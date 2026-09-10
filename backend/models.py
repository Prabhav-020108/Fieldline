from sqlalchemy import create_engine, Column, String, Integer, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    equipment_id = Column(String, index=True)
    site_id = Column(String, index=True)
    fault_description = Column(String)
    resolution = Column(String, nullable=True)
    status = Column(String, default="open")

class InventoryItem(Base):
    __tablename__ = "inventory_items"
    id = Column(String, primary_key=True)
    part_number = Column(String, index=True)
    name = Column(String)
    location = Column(String)
    quantity = Column(Integer, default=0)

class DispatchEvent(Base):
    __tablename__ = "dispatch_events"
    id = Column(String, primary_key=True)
    job_id = Column(String, ForeignKey("jobs.id"))
    technician_id = Column(String)
    event_type = Column(String)   # delay / reroute / assign
    timestamp = Column(String)

engine = create_engine("sqlite:///./db.sqlite3")
SessionLocal = sessionmaker(bind=engine)

def init_db():
    Base.metadata.create_all(engine)