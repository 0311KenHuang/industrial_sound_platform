from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
APP_DIR = BASE_DIR / "app"
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "platform.db"
STATIC_DIR = APP_DIR / "static"
