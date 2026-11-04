"""HTTP API. Runs standalone (PC or Raspberry Pi); the frontend is a separate static app."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import dir_matching, http, recorder
from .config import CORS_ORIGINS, RECORD, STATIC_DIR, tomtom_key
from .feeds import cita, dir_est, tomtom
from .http import FeedError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

DIRECTION = "^(to_work|to_home)$"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(recorder.run_forever()) if RECORD else None
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


@app.get("/", include_in_schema=False)
async def root(request: Request):
    # This server is only the API; point people to the app.
    host = request.url.hostname
    return HTMLResponse(
        f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">
        <title>Commute API</title>
        <body style="background:#05070b;color:#e9eef6;font:16px system-ui;padding:40px;line-height:1.6">
        <h2 style="margin-top:0">Commute API is running</h2>
        <p>This is the backend. Open the app:</p>
        <ul><li><a style="color:#45d8ff" href="http://{host}:4173">http://{host}:4173</a> (frontend/run.ps1)</li>
        <li><a style="color:#45d8ff" href="http://{host}:5173">http://{host}:5173</a> (dev server)</li></ul>
        <p style="color:#6c778a">API docs: <a style="color:#a6b0c0" href="/docs">/docs</a></p></body>""")


@app.get("/api/status")
async def status():
    return {"tomtom_key": bool(tomtom_key()), "recording": RECORD, "recordings": recorder.stats()}


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
