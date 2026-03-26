import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/sqlite/laptop_ai_box.db")
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "")
    ADMIN_USER: str = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", "admin")
    
    HLS_OUTPUT_DIR: str = os.getenv("HLS_OUTPUT_DIR", "data/media/hls")
    SNAPSHOTS_DIR: str = os.getenv("SNAPSHOTS_DIR", "data/media/snapshots")
    CLIPS_DIR: str = os.getenv("CLIPS_DIR", "data/media/clips")
    
    class Config:
        env_file = ".env"

settings = Settings()

# Ensure directories exist
os.makedirs(settings.HLS_OUTPUT_DIR, exist_ok=True)
os.makedirs(settings.SNAPSHOTS_DIR, exist_ok=True)
os.makedirs(settings.CLIPS_DIR, exist_ok=True)
os.makedirs("data/sqlite", exist_ok=True)
