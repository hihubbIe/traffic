"""SQLite store for everything the collector records (the model's training data).

One file, WAL mode so the API and the collector (separate processes) can use it at once.
Timestamps are integer UTC epoch seconds.
"""
import json
import sqlite3
import time
from contextlib import contextmanager

from .config import RECORDINGS_DIR

DB_PATH = RECORDINGS_DIR / "commute.sqlite"

SCHEMA = """
-- Measurement sites: CITA loops, DIR Est stations, TomTom key segments, weather places.
CREATE TABLE IF NOT EXISTS sites (
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, ext_id TEXT NOT NULL, road TEXT,
  lat REAL, lon REAL, direction TEXT, meta TEXT, UNIQUE (source, ext_id));

-- Loop detectors (CITA, DIR Est): one row per site per measurement time.
CREATE TABLE IF NOT EXISTS obs_sensor (
  site INTEGER NOT NULL, ts INTEGER NOT NULL, speed REAL, flow REAL, occupancy REAL,
  PRIMARY KEY (site, ts)) WITHOUT ROWID;

-- TomTom flow on key segments of the routes.
CREATE TABLE IF NOT EXISTS obs_segment (
  site INTEGER NOT NULL, ts INTEGER NOT NULL, speed REAL, free_speed REAL,
  travel_s REAL, free_travel_s REAL, confidence REAL, closed INTEGER,
  PRIMARY KEY (site, ts)) WITHOUT ROWID;

-- TomTom door-to-door route times (the target the model learns).
CREATE TABLE IF NOT EXISTS obs_route (
  route TEXT NOT NULL, direction TEXT NOT NULL, ts INTEGER NOT NULL,
  travel_s REAL, free_s REAL, historic_s REAL, delay_s REAL, length_m REAL,
  traffic TEXT, passes TEXT, PRIMARY KEY (route, direction, ts)) WITHOUT ROWID;

-- CITA variable message signs (official LU travel times).
CREATE TABLE IF NOT EXISTS obs_sign (
  sign TEXT NOT NULL, destination TEXT NOT NULL, ts INTEGER NOT NULL, minutes INTEGER,
  PRIMARY KEY (sign, destination, ts)) WITHOUT ROWID;

-- Weather at a few places along the corridor.
CREATE TABLE IF NOT EXISTS obs_weather (
  place TEXT NOT NULL, ts INTEGER NOT NULL, temp REAL, precip REAL, rain REAL, snowfall REAL,
  code INTEGER, wind REAL, visibility REAL, cloud REAL, PRIMARY KEY (place, ts)) WITHOUT ROWID;

-- Trains through Thionville / Luxembourg with realtime changes (SNCF GTFS-RT).
CREATE TABLE IF NOT EXISTS obs_rail (
  trip TEXT NOT NULL, ts INTEGER NOT NULL, relationship INTEGER, delay_thionville INTEGER,
  max_delay INTEGER, origin TEXT, destination TEXT, PRIMARY KEY (trip, ts)) WITHOUT ROWID;

-- Incidents, roadworks, closures, rail alerts: lifetime of each event as observed.
CREATE TABLE IF NOT EXISTS events (
  source TEXT NOT NULL, ext_id TEXT NOT NULL, first_seen INTEGER, last_seen INTEGER,
  kind TEXT, road TEXT, lat REAL, lon REAL, start TEXT, end_ TEXT, payload TEXT,
  PRIMARY KEY (source, ext_id));

-- Your own trips: the best ground truth.
CREATE TABLE IF NOT EXISTS trips (
  id INTEGER PRIMARY KEY, direction TEXT, route TEXT, depart_ts INTEGER, arrive_ts INTEGER, note TEXT);

-- Collector health and TomTom request budget.
CREATE TABLE IF NOT EXISTS collector_runs (
  ts INTEGER NOT NULL, job TEXT NOT NULL, ok INTEGER, rows INTEGER, ms INTEGER, error TEXT);
CREATE INDEX IF NOT EXISTS collector_runs_job_ts ON collector_runs (job, ts);
CREATE TABLE IF NOT EXISTS seen_files (source TEXT NOT NULL, name TEXT NOT NULL, ts INTEGER,
  PRIMARY KEY (source, name)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS api_usage (day TEXT NOT NULL, api TEXT NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY (day, api));
"""


def connect() -> sqlite3.Connection:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript(SCHEMA)
    return con


@contextmanager
def tx(con: sqlite3.Connection):
    """One short write transaction. Never await inside it: the database stays locked meanwhile."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def now() -> int:
    return int(time.time())


def site_id(con: sqlite3.Connection, source: str, ext_id: str, road=None, lat=None, lon=None,
            direction=None, meta=None, _cache: dict = {}) -> int:
    key = (source, ext_id)
    if key in _cache:
        return _cache[key]
    con.execute(
        "INSERT INTO sites (source, ext_id, road, lat, lon, direction, meta) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(source, ext_id) DO UPDATE SET road=coalesce(excluded.road, road), "
        "lat=coalesce(excluded.lat, lat), lon=coalesce(excluded.lon, lon), "
        "direction=coalesce(excluded.direction, direction), meta=coalesce(excluded.meta, meta)",
        (source, ext_id, road, lat, lon, direction, json.dumps(meta) if meta is not None else None))
    sid = con.execute("SELECT id FROM sites WHERE source=? AND ext_id=?", key).fetchone()[0]
    _cache[key] = sid
    return sid


def upsert_event(con, source: str, ext_id: str, kind=None, road=None, lat=None, lon=None,
                 start=None, end=None, payload=None) -> None:
    t = now()
    con.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source, ext_id) DO UPDATE SET "
        "last_seen=excluded.last_seen, end_=coalesce(excluded.end_, end_), payload=excluded.payload",
        (source, ext_id, t, t, kind, road, lat, lon, start, end, json.dumps(payload, ensure_ascii=False)))
