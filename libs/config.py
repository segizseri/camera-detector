import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/sqlite/laptop_ai_box.db")
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "")
    AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "true").lower() not in {"0", "false", "no", "off"}
    ADMIN_USER: str = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASS: str = os.getenv("ADMIN_PASS", "admin")
    # Ключ подписи cookie сессии; если пусто, используется ENCRYPTION_KEY.
    SESSION_SECRET: str = os.getenv("SESSION_SECRET", "")
    HLS_IDLE_TIMEOUT_SECONDS: int = int(os.getenv("HLS_IDLE_TIMEOUT_SECONDS", "180"))
    RETENTION_SWEEP_INTERVAL_SECONDS: int = int(os.getenv("RETENTION_SWEEP_INTERVAL_SECONDS", "3600"))
    
    HLS_OUTPUT_DIR: str = os.getenv("HLS_OUTPUT_DIR", "data/media/hls")
    SNAPSHOTS_DIR: str = os.getenv("SNAPSHOTS_DIR", "data/media/snapshots")
    CLIPS_DIR: str = os.getenv("CLIPS_DIR", "data/media/clips")
    MODELS_DIR: str = os.getenv("MODELS_DIR", "data/models")
    ACTION_MODEL_PATH: str = os.getenv("ACTION_MODEL_PATH", "data/models/action_lstm.pt")
    DETECTION_TESTS_DIR: str = os.getenv("DETECTION_TESTS_DIR", "data/media/detection-tests")
    DETECTION_TEST_MAX_UPLOAD_MB: int = int(os.getenv("DETECTION_TEST_MAX_UPLOAD_MB", "1024"))
    DETECTION_TEST_MAX_DURATION_SECONDS: int = int(os.getenv("DETECTION_TEST_MAX_DURATION_SECONDS", "3600"))

    # YOLO-Pose input size and frame rate the ActionLSTM dataset is extracted with
    # (scripts/train_lstm.py --extract). Live cameras and detection tests must match,
    # otherwise keypoints differ and 30-frame windows cover a different duration.
    POSE_IMGSZ: int = int(os.getenv("POSE_IMGSZ", "320"))
    ACTION_SAMPLE_FPS: float = float(os.getenv("ACTION_SAMPLE_FPS", "5"))

settings = Settings()

# Ensure directories exist
os.makedirs(settings.HLS_OUTPUT_DIR, exist_ok=True)
os.makedirs(settings.SNAPSHOTS_DIR, exist_ok=True)
os.makedirs(settings.CLIPS_DIR, exist_ok=True)
os.makedirs(settings.MODELS_DIR, exist_ok=True)
os.makedirs(settings.DETECTION_TESTS_DIR, exist_ok=True)
os.makedirs("data/sqlite", exist_ok=True)
