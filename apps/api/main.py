import os
from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
from libs.database import engine, Base
from libs.models import Camera, Event, Webhook
from apps.api.routers import nvr, cameras, events, webhooks, settings, stats, buses, visitors

Base.metadata.create_all(bind=engine)

# Auto-migration: Add missing columns to existing tables
def auto_migrate():
    """Inspect all model tables and ALTER TABLE to add any missing columns."""
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        for col in table.columns:
            if col.name not in existing_cols:
                col_type = col.type.compile(engine.dialect)
                default_clause = ""
                if col.default is not None:
                    default_val = col.default.arg
                    if isinstance(default_val, bool):
                        default_clause = f" DEFAULT {1 if default_val else 0}"
                    elif isinstance(default_val, (int, float)):
                        default_clause = f" DEFAULT {default_val}"
                    elif isinstance(default_val, str):
                        default_clause = f" DEFAULT '{default_val}'"
                nullable = "" if col.nullable else " NOT NULL"
                # SQLite doesn't support NOT NULL without default on ALTER
                if not col.nullable and not default_clause:
                    nullable = ""
                stmt = f'ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}{nullable}'
                with engine.begin() as conn:
                    conn.execute(text(stmt))
                print(f"[migrate] Added column {table_name}.{col.name} ({col_type}{default_clause})")

try:
    auto_migrate()
except Exception as e:
    print(f"[migrate] Warning: {e}")

# Auto-migration: Create default bus for cameras without one
def migrate_buses():
    from libs.database import SessionLocal
    from libs.models import Bus, Camera
    import uuid
    db = SessionLocal()
    try:
        cams_without_bus = db.query(Camera).filter(Camera.bus_id == None).all()
        if cams_without_bus:
            default_bus = db.query(Bus).filter(Bus.name == "Default Bus").first()
            if not default_bus:
                default_bus = Bus(id=str(uuid.uuid4()), name="Default Bus", license_plate="AUTO")
                db.add(default_bus)
                db.commit()
                db.refresh(default_bus)
            
            for cam in cams_without_bus:
                cam.bus_id = default_bus.id
            db.commit()
    finally:
        db.close()

migrate_buses()

app = FastAPI(title="Camera Detector AI Box")

os.makedirs("data/media/hls", exist_ok=True)
os.makedirs("data/media/snapshots", exist_ok=True)
os.makedirs("data/media/clips", exist_ok=True)
os.makedirs("apps/api/static", exist_ok=True)

app.mount("/static", StaticFiles(directory="apps/api/static"), name="static")
app.mount("/media", StaticFiles(directory="data/media"), name="media")

templates = Jinja2Templates(directory="apps/api/templates")

app.include_router(nvr.router, prefix="/api/nvr", tags=["NVR"])
app.include_router(cameras.router, prefix="/api/cameras", tags=["Cameras"])
app.include_router(events.router, prefix="/api/events", tags=["Events"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(stats.router, prefix="/api/stats", tags=["Statistics"])
app.include_router(buses.router, prefix="/api/buses", tags=["Buses"])
app.include_router(visitors.router, prefix="/api/visitors", tags=["Visitors"])

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("apps/api/static/favicon.png")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/nvr", response_class=HTMLResponse)
async def nvr_page(request: Request):
    return templates.TemplateResponse("nvr.html", {"request": request})

@app.get("/cameras", response_class=HTMLResponse)
async def cameras_page(request: Request):
    return templates.TemplateResponse("cameras.html", {"request": request})

@app.get("/cameras/{camera_id}", response_class=HTMLResponse)
async def camera_detail_page(request: Request, camera_id: str):
    return templates.TemplateResponse("camera_detail.html", {"request": request, "camera_id": camera_id})

@app.get("/ai", response_class=HTMLResponse)
async def ai_page(request: Request):
    return templates.TemplateResponse("ai.html", {"request": request})

@app.get("/events-page", response_class=HTMLResponse)
async def events_page(request: Request):
    return templates.TemplateResponse("events.html", {"request": request})

@app.get("/integrations/webhooks", response_class=HTMLResponse)
async def webhooks_page(request: Request):
    return templates.TemplateResponse("webhooks.html", {"request": request})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/reports/passengers", response_class=HTMLResponse)
async def passenger_report_page(request: Request):
    return templates.TemplateResponse("passenger_report.html", {"request": request})

@app.get("/buses", response_class=HTMLResponse)
async def buses_page(request: Request):
    return templates.TemplateResponse("buses.html", {"request": request})

@app.get("/finetune", response_class=HTMLResponse)
async def finetune_page(request: Request):
    import os
    dataset_dir = "data/dataset"
    folders = []
    if os.path.exists(dataset_dir):
        folders = [f for f in os.listdir(dataset_dir) if os.path.isdir(os.path.join(dataset_dir, f))]
    return templates.TemplateResponse("finetune.html", {"request": request, "dataset_folders": folders})

@app.get("/visitors", response_class=HTMLResponse)
async def visitors_page(request: Request):
    return templates.TemplateResponse("visitors.html", {"request": request})

@app.get("/visitors/{visitor_id}", response_class=HTMLResponse)
async def visitor_detail_page(request: Request, visitor_id: str):
    return templates.TemplateResponse("visitor_detail.html", {"request": request, "visitor_id": visitor_id})
