from pathlib import Path
import os

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("TRAFFIC_DATA_DIR", BACKEND_DIR / "data"))
STATIC_DIR = DATA_DIR / "static"
RECORDINGS_DIR = DATA_DIR / "recordings"

load_dotenv(BACKEND_DIR / ".env")


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def tomtom_key() -> str:
    # Read on each call so editing .env + restarting is the only step needed.
    return os.getenv("TOMTOM_API_KEY", "").strip()


RECORD = _flag("RECORD", True)

# Origins allowed to call the API from a browser ("*" = any, fine on a home network).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
RECORD_TOMTOM = _flag("RECORD_TOMTOM", True)

# Study area (lon/lat): Thionville to north of Luxembourg City.
BBOX = (5.80, 49.28, 6.40, 49.66)

USER_AGENT = "traffic-belval-thionville/0.1 (personal project)"
