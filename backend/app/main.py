"""HTTP API. Runs standalone (PC or Raspberry Pi); the frontend is a separate static app."""
import asyncio
import json
import logging
import shutil
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import budget, collector, db, dir_matching, http
from .config import COLLECT_IN_API, CORS_ORIGINS, DATA_DIR, FRONTEND_DIST, STATIC_DIR, tomtom_key
from .feeds import cita, dir_est, tomtom
from .http import FeedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

DIRECTION = "^(to_work|to_home)$"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(collector.run_forever()) if COLLECT_IN_API else None
    yield
    if task:
        task.cancel()
    await http.close()


app = FastAPI(title="Home-Work traffic", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


async def _guard(coro):
    try:
        return await coro
    except tomtom.NoKey as e:
        raise HTTPException(503, str(e))
    except FeedError as e:
        raise HTTPException(502, str(e))


@app.get("/api/status")
async def status():
    disk = shutil.disk_usage(DATA_DIR)
    return {
        "tomtom_key": bool(tomtom_key()),
        "collector_in_api": COLLECT_IN_API,
        "collector": collector.health(),
        "tomtom_budget": budget.summary(),
        "db_mb": round(db.DB_PATH.stat().st_size / 1e6, 1) if db.DB_PATH.exists() else 0,
        "disk_free_gb": round(disk.free / 1e9, 1),
    }


class TripEvent(BaseModel):
    action: Literal["depart", "arrive", "cancel"]
    direction: Literal["to_work", "to_home"] | None = None
    route: str | None = None
    note: str | None = None


@app.get("/api/trips")
async def trips(limit: int = 50):
    con = db.connect()
    try:
        rows = con.execute("SELECT id, direction, route, depart_ts, arrive_ts, note FROM trips ORDER BY id DESC LIMIT ?",
                           (limit,)).fetchall()
    finally:
        con.close()
    return [dict(zip(("id", "direction", "route", "depart_ts", "arrive_ts", "note"), r)) for r in rows]


@app.post("/api/trips")
async def trip_event(ev: TripEvent):
    """Your own trips (ground truth): 'depart' opens a trip, 'arrive' closes the open one."""
    con = db.connect()
    try:
        open_trip = con.execute("SELECT id FROM trips WHERE arrive_ts IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if ev.action == "depart":
            if open_trip:  # a forgotten trip: keep it, but unfinished
                con.execute("UPDATE trips SET note = coalesce(note, '') || ' [not closed]' WHERE id = ?", open_trip)
            con.execute("INSERT INTO trips (direction, route, depart_ts, note) VALUES (?,?,?,?)",
                        (ev.direction, ev.route, db.now(), ev.note))
        elif not open_trip:
            raise HTTPException(409, "No trip in progress")
        elif ev.action == "arrive":
            con.execute("UPDATE trips SET arrive_ts = ?, route = coalesce(?, route) WHERE id = ?",
                        (db.now(), ev.route, open_trip[0]))
        else:
            con.execute("DELETE FROM trips WHERE id = ?", open_trip)
        row = con.execute("SELECT id, direction, route, depart_ts, arrive_ts FROM trips ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        con.close()
    return dict(zip(("id", "direction", "route", "depart_ts", "arrive_ts"), row)) if row else {}


@app.get("/api/cita/traffic")
async def cita_traffic():
    return await _guard(cita.traffic_status())


@app.get("/api/cita/events")
async def cita_events():
    return await _guard(cita.events())


@app.get("/api/cita/travel-times")
async def cita_travel_times():
    return await _guard(cita.travel_times())


@app.get("/api/cita/cameras")
async def cita_cameras():
    return await _guard(cita.cameras())


@app.get("/api/cita/interchanges")
async def cita_interchanges():
    return await _guard(cita.interchanges())


@app.get("/api/dir/stations")
async def dir_stations():
    return await _guard(dir_est.stations())


@app.get("/api/dir/match")
async def dir_match():
    return dir_matching.propose()


@app.post("/api/dir/match/apply")
async def dir_match_apply():
    return {"applied": dir_matching.apply_confident()}


@app.get("/api/tomtom/flow/{z}/{x}/{y}.png")
async def tomtom_flow(z: int, x: int, y: int, style: str = "relative0"):
    try:
        png = await tomtom.flow_tile(z, x, y, style)
    except (tomtom.NoKey, FeedError):
        return Response(status_code=204)
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=120"})


@app.get("/api/tomtom/incidents")
async def tomtom_incidents():
    return await _guard(tomtom.incidents())


@app.get("/api/corridors")
async def corridors():
    return tomtom.load_corridors()


@app.get("/api/corridors/now")
async def corridors_now(direction: str = Query("to_work", pattern=DIRECTION)):
    return await _guard(tomtom.corridors_now(direction))


@app.get("/api/corridors/{corridor_id}/curve")
async def corridor_curve(corridor_id: str, direction: str = Query("to_work", pattern=DIRECTION),
                         day: date | None = None, start: str = "06:00", end: str = "09:30"):
    return await _guard(tomtom.departure_curve(corridor_id, direction, day or date.today(), start, end))


@app.get("/api/static/{name}")
async def static_layer(name: str):
    path = STATIC_DIR / f"{name}.json"
    if not path.is_file() or path.parent != STATIC_DIR:
        raise HTTPException(404)
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


if (FRONTEND_DIST / "index.html").exists():
    # The built frontend, so a phone only needs this server's address.
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="app")
else:
    @app.get("/", include_in_schema=False)
    async def root(request: Request):
        host = request.url.hostname
        return HTMLResponse(
            f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
            <title>Commute API</title>
            <body style="background:#05070b;color:#e9eef6;font:16px system-ui;padding:40px;line-height:1.6">
            <h2 style="margin-top:0">Commute API is running</h2>
            <p>The app isn't built here (no frontend/dist). Open it from the frontend server:</p>
            <ul><li><a style="color:#45d8ff" href="http://{host}:4173">http://{host}:4173</a> (frontend/run.ps1)</li>
            <li><a style="color:#45d8ff" href="http://{host}:5173">http://{host}:5173</a> (dev server)</li></ul>
            <p style="color:#6c778a">API docs: <a style="color:#a6b0c0" href="/docs">/docs</a> ·
            health: <a style="color:#a6b0c0" href="/api/status">/api/status</a></p></body>""")
