import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from libs import auth
from libs.config import settings as app_settings
from libs.database import engine, Base
from libs.models import Camera, Event, Webhook
from apps.api.routers import nvr, cameras, events, webhooks, settings, stats, buses, visitors, system, detection_tests, dataset

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

def migrate_camera_credentials():
    from libs.camera_migration import migrate_rtsp_credentials
    from libs.database import SessionLocal
    db = SessionLocal()
    try:
        updated = migrate_rtsp_credentials(db)
        if updated:
            print(f"[migrate] Stripped credentials from {updated} camera RTSP URLs")
    finally:
        db.close()

migrate_camera_credentials()

@asynccontextmanager
async def lifespan(app: FastAPI):
    cameras.start_hls_reaper()
    yield

app = FastAPI(title="Camera Detector AI Box", lifespan=lifespan)
app.middleware("http")(auth.auth_middleware)

os.makedirs("data/media/hls", exist_ok=True)
os.makedirs("data/media/snapshots", exist_ok=True)
os.makedirs("data/media/clips", exist_ok=True)
os.makedirs("data/media/detection-tests", exist_ok=True)
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
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(detection_tests.router, prefix="/api/detection-tests", tags=["Detection tests"])
app.include_router(dataset.router, prefix="/api/dataset", tags=["Dataset"])

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("apps/api/static/favicon.png")

def _login_page(request: Request, next_url: str, *, error: str | None = None, username: str = "", status_code: int = 200):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "next": next_url, "error": error, "username": username},
        status_code=status_code,
    )

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next_url: str = Query("/", alias="next")):
    if not app_settings.AUTH_ENABLED or auth.read_session(request.cookies.get(auth.SESSION_COOKIE)):
        return RedirectResponse(auth.safe_next(next_url), status_code=303)
    return _login_page(request, auth.safe_next(next_url))

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    form = await request.form()
    next_url = auth.safe_next(str(form.get("next") or "/"))
    if not app_settings.AUTH_ENABLED:
        return RedirectResponse(next_url, status_code=303)
    username = str(form.get("username") or "").strip()
    client = request.client.host if request.client else "unknown"

    locked = auth.login_lockout_remaining(client)
    if locked:
        minutes = max(1, round(locked / 60))
        return _login_page(request, next_url, username=username, status_code=429,
                           error=f"Слишком много неудачных попыток. Повторите через {minutes} мин.")

    if not auth.check_credentials(username, str(form.get("password") or "")):
        auth.register_login_failure(client)
        await asyncio.sleep(0.6)  # замедляем подбор пароля
        return _login_page(request, next_url, username=username, status_code=401,
                           error="Неверный логин или пароль.")

    auth.reset_login_failures(client)
    response = RedirectResponse(next_url, status_code=303)
    auth.set_session_cookie(response, request, username, remember=form.get("remember") == "on")
    return response

@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    auth.clear_session_cookie(response)
    return response

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

@app.get("/detection-test", response_class=HTMLResponse)
async def detection_test_page(request: Request):
    return templates.TemplateResponse(request, "detection_test.html")

@app.get("/events-page", response_class=HTMLResponse)
async def events_page(request: Request):
    return templates.TemplateResponse("events.html", {"request": request})

@app.get("/integrations/webhooks", response_class=HTMLResponse)
async def webhooks_page(request: Request):
    return templates.TemplateResponse("webhooks.html", {"request": request})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return templates.TemplateResponse("reports.html", {"request": request})

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
