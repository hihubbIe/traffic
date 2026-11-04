"""Daily TomTom request budget, shared by the API and the collector through the database.

The collector stops at (budget - reserve) so the app keeps some requests for you.
Counts survive restarts; the day rolls over at local midnight.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from . import db
from .config import TOMTOM_DAILY_BUDGET, TOMTOM_APP_RESERVE

TZ = ZoneInfo("Europe/Luxembourg")


class BudgetExceeded(Exception):
    pass


def _today() -> str:
    return datetime.now(TZ).date().isoformat()


def used(con=None) -> int:
    con = con or db.connect()
    row = con.execute("SELECT coalesce(sum(n), 0) FROM api_usage WHERE day=? AND api != 'tiles'", (_today(),)).fetchone()
    return row[0]


def consume(api: str, n: int = 1, background: bool = False) -> None:
    """Count n requests; raise BudgetExceeded instead if they don't fit."""
    con = db.connect()
    try:
        with db.tx(con):
            if api != "tiles":
                limit = TOMTOM_DAILY_BUDGET - (TOMTOM_APP_RESERVE if background else 0)
                if used(con) + n > limit:
                    raise BudgetExceeded(f"TomTom daily budget reached ({limit} requests)")
            con.execute("INSERT INTO api_usage VALUES (?,?,?) ON CONFLICT(day, api) DO UPDATE SET n = n + excluded.n",
                        (_today(), api, n))
    finally:
        con.close()


def summary() -> dict:
    con = db.connect()
    try:
        rows = con.execute("SELECT api, n FROM api_usage WHERE day=?", (_today(),)).fetchall()
    finally:
        con.close()
    by_api = dict(rows)
    return {"day": _today(), "used": sum(v for k, v in by_api.items() if k != "tiles"),
            "budget": TOMTOM_DAILY_BUDGET, "reserve_for_app": TOMTOM_APP_RESERVE, "by_api": by_api}
