import os
from fastapi import FastAPI, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from libs.database import engine, Base
from libs.models import Camera, Event, Webhook
from apps.api.routers import nvr, cameras, events, webhooks

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Laptop AI Box MVP")

# Check if static dirs exist, if not, wait for them
os.makedirs("data/media/hls", exist_ok=True)
os.makedirs("data/media/snapshots", exist_ok=True)
os.makedirs("data/media/clips", exist_ok=True)

app.mount("/media/hls", StaticFiles(directory="data/media/hls"), name="hls")
app.mount("/media/snapshots", StaticFiles(directory="data/media/snapshots"), name="snapshots")
app.mount("/media/clips", StaticFiles(directory="data/media/clips"), name="clips")

templates = Jinja2Templates(directory="apps/api/templates")

app.include_router(nvr.router, prefix="/api/nvr", tags=["NVR"])
app.include_router(cameras.router, prefix="/api/cameras", tags=["Cameras"])
app.include_router(events.router, prefix="/api/events", tags=["Events"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])

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
