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


# Run the collector inside the API process (handy on a PC). On the Pi it runs as its own service.
COLLECT_IN_API = _flag("COLLECT_IN_API", True)

# TomTom requests per day (non-tile). Check your plan's free tier on the TomTom dashboard.
TOMTOM_DAILY_BUDGET = int(os.getenv("TOMTOM_DAILY_BUDGET", "2300"))
# Part of the budget the collector leaves for the app itself.
TOMTOM_APP_RESERVE = int(os.getenv("TOMTOM_APP_RESERVE", "300"))

# Built frontend served at "/" when present, so a phone only needs the backend's address.
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", BACKEND_DIR.parent / "frontend" / "dist"))

# Origins allowed to call the API from a browser ("*" = any, fine on a home network).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Study area (lon/lat): Thionville to north of Luxembourg City.
BBOX = (5.80, 49.28, 6.40, 49.66)

USER_AGENT = "traffic-belval-thionville/0.1 (personal project)"
