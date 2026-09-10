from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.agents.route_compliance import evaluate_route_compliance
from backend.app.agents.triage import generate_triage
from backend.app.db import connect, hydrate_alert, hydrate_trip, init_db, row_to_dict, rows_to_dicts, utc_now
from backend.app.gtfs.static_data import DEMO_ROUTE, ON_ROUTE_TRACE, WRONG_BUS_TRACE, resolve_destination

app = FastAPI(title="Guardian API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateTripRequest(BaseModel):
    rider_id: str = "rider_nguyen"
    destination: str = "Westminster Clinic"
    mode: str = "voice"


class LocationRequest(BaseModel):
    lat: float
    lon: float
    source: str = "browser"
    recorded_at: str | None = None


class DutyRequest(BaseModel):
    on_duty: bool


class PermissionRequest(BaseModel):
    location: bool = Field(default=True)
    notifications: bool = Field(default=True)
    microphone: bool = Field(default=True)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active.discard(websocket)

    async def broadcast(self, event: str, payload: dict) -> None:
        stale: list[WebSocket] = []
        for websocket in self.active:
            try:
                await websocket.send_json({"event": event, "payload": payload})
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


manager = ConnectionManager()


@app.on_event("startup")
async def startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "guardian-api"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    await websocket.send_json({"event": "snapshot", "payload": snapshot()})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/snapshot")
def snapshot() -> dict:
    return {
        "riders": list_riders(),
        "dispatchers": list_dispatchers(),
        "trips": list_trips(),
        "alerts": list_alerts(),
    }


@app.get("/riders")
def list_riders() -> list[dict]:
    with connect() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM riders ORDER BY name").fetchall())
    for row in rows:
        row["permissions"] = json.loads(row.pop("permissions_json"))
    return rows


@app.patch("/riders/{rider_id}/permissions")
async def update_permissions(rider_id: str, request: PermissionRequest) -> dict:
    permissions = request.model_dump()
    with connect() as conn:
        row = row_to_dict(conn.execute("SELECT * FROM riders WHERE id = ?", (rider_id,)).fetchone())
        if not row:
            raise HTTPException(status_code=404, detail="Rider not found")
        conn.execute("UPDATE riders SET permissions_json = ? WHERE id = ?", (json.dumps(permissions), rider_id))
    await manager.broadcast("snapshot", snapshot())
    return {"rider_id": rider_id, "permissions": permissions, "ready": all(permissions.values())}


@app.get("/dispatchers")
def list_dispatchers() -> list[dict]:
    with connect() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM dispatchers ORDER BY name").fetchall())
    for row in rows:
        row["on_duty"] = bool(row["on_duty"])
    return rows


@app.post("/dispatchers/{dispatcher_id}/duty")
async def set_dispatcher_duty(dispatcher_id: str, request: DutyRequest) -> dict:
    with connect() as conn:
        row = row_to_dict(conn.execute("SELECT * FROM dispatchers WHERE id = ?", (dispatcher_id,)).fetchone())
        if not row:
            raise HTTPException(status_code=404, detail="Dispatcher not found")
        conn.execute("UPDATE dispatchers SET on_duty = ? WHERE id = ?", (1 if request.on_duty else 0, dispatcher_id))
    await manager.broadcast("snapshot", snapshot())
    return {"dispatcher_id": dispatcher_id, "on_duty": request.on_duty}


@app.post("/trips")
async def create_trip(request: CreateTripRequest) -> dict:
    resolution = resolve_destination(request.destination)
    with connect() as conn:
        rider = row_to_dict(conn.execute("SELECT * FROM riders WHERE id = ?", (request.rider_id,)).fetchone())
        if not rider:
            raise HTTPException(status_code=404, detail="Rider not found")
        permissions = json.loads(rider["permissions_json"])
        if not all(permissions.values()):
            raise HTTPException(status_code=409, detail={"message": "Critical permissions missing", "permissions": permissions})

        trip_id = f"trip_{uuid.uuid4().hex[:8]}"
        milestones = [
            {"label": "Trip confirmed", "complete": True},
            {"label": f"Board {resolution['route']['name']}", "complete": False},
            {"label": "Approaching Westminster Clinic", "complete": False},
            {"label": "Arrived", "complete": False},
        ]
        now = utc_now()
        conn.execute(
            """
            INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trip_id,
                request.rider_id,
                rider["organization_id"],
                resolution["destination"]["name"],
                resolution["route"]["id"],
                resolution["route"]["name"],
                "active",
                "green",
                json.dumps(resolution["route"]["shape"]),
                json.dumps(milestones),
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, None, "trip_created", json.dumps({"mode": request.mode, "destination": request.destination}), now),
        )
    created = get_trip(trip_id)
    await manager.broadcast("trip_created", created)
    await manager.broadcast("snapshot", snapshot())
    return {**created, "resolution": resolution}


@app.get("/trips")
def list_trips() -> list[dict]:
    with connect() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM trips ORDER BY created_at DESC").fetchall())
    return [hydrate_trip(row) for row in rows]


@app.get("/trips/{trip_id}")
def get_trip(trip_id: str) -> dict:
    with connect() as conn:
        trip = row_to_dict(conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone())
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        locations = rows_to_dicts(
            conn.execute("SELECT lat, lon, source, recorded_at FROM locations WHERE trip_id = ? ORDER BY id", (trip_id,)).fetchall()
        )
        alerts = rows_to_dicts(conn.execute("SELECT * FROM alerts WHERE trip_id = ? ORDER BY created_at DESC", (trip_id,)).fetchall())
        rider = row_to_dict(conn.execute("SELECT name, preferred_language, phone FROM riders WHERE id = ?", (trip["rider_id"],)).fetchone())
    return {
        **hydrate_trip(trip),
        "rider": rider,
        "locations": locations,
        "alerts": [hydrate_alert(alert) for alert in alerts],
    }


@app.post("/trips/{trip_id}/locations")
async def add_location(trip_id: str, request: LocationRequest) -> dict:
    recorded_at = request.recorded_at or datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        trip = row_to_dict(conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone())
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        conn.execute(
            "INSERT INTO locations (trip_id, lat, lon, source, recorded_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, request.lat, request.lon, request.source, recorded_at),
        )
        locations = rows_to_dicts(
            conn.execute("SELECT lat, lon, source, recorded_at FROM locations WHERE trip_id = ? ORDER BY id", (trip_id,)).fetchall()
        )

    route_shape = tuple(tuple(point) for point in json.loads(trip["route_shape_json"]))
    compliance = evaluate_route_compliance(locations, route_shape)
    await update_trip_status(trip_id, compliance)
    if compliance["deviation_type"]:
        await create_alert_if_needed(trip_id, compliance)

    hydrated = get_trip(trip_id)
    await manager.broadcast("location_added", {"trip": hydrated, "compliance": compliance})
    await manager.broadcast("snapshot", snapshot())
    return {"trip": hydrated, "compliance": compliance}


async def update_trip_status(trip_id: str, compliance: dict) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE trips SET status = ?, severity = ?, updated_at = ? WHERE id = ?",
            (compliance["status"], compliance["severity"], utc_now(), trip_id),
        )


async def create_alert_if_needed(trip_id: str, compliance: dict) -> None:
    with connect() as conn:
        existing = row_to_dict(
            conn.execute(
                "SELECT * FROM alerts WHERE trip_id = ? AND status IN ('open', 'claimed', 'critical')",
                (trip_id,),
            ).fetchone()
        )
        if existing:
            return
        trip = row_to_dict(conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone())
        rider = row_to_dict(conn.execute("SELECT name, phone FROM riders WHERE id = ?", (trip["rider_id"],)).fetchone())
        dispatcher = row_to_dict(
            conn.execute(
                "SELECT id FROM dispatchers WHERE organization_id = ? AND on_duty = 1 ORDER BY name LIMIT 1",
                (trip["organization_id"],),
            ).fetchone()
        )
        event = {
            "rider_name": rider["name"],
            "rider_phone": rider["phone"],
            "destination_name": trip["destination_name"],
            "route_name": trip["route_name"],
            **compliance,
        }
        triage = generate_triage(event)
        alert_id = f"alert_{uuid.uuid4().hex[:8]}"
        now = utc_now()
        conn.execute(
            """
            INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                trip_id,
                trip["organization_id"],
                compliance["deviation_type"],
                1,
                compliance["severity"],
                "open",
                dispatcher["id"] if dispatcher else None,
                json.dumps(triage),
                now,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, alert_id, "alert_created", json.dumps(event), now),
        )
    asyncio.create_task(escalate_later(alert_id))
    await manager.broadcast("alert_created", get_alert(alert_id))


async def escalate_later(alert_id: str) -> None:
    await asyncio.sleep(180)
    await escalate_alert(alert_id)


@app.post("/alerts/{alert_id}/claim")
async def claim_alert(alert_id: str, dispatcher_id: str = "dispatcher_lan") -> dict:
    with connect() as conn:
        alert = row_to_dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        dispatcher = row_to_dict(conn.execute("SELECT * FROM dispatchers WHERE id = ?", (dispatcher_id,)).fetchone())
        if not dispatcher:
            raise HTTPException(status_code=404, detail="Dispatcher not found")
        now = utc_now()
        conn.execute(
            "UPDATE alerts SET status = 'claimed', assigned_dispatcher_id = ?, updated_at = ? WHERE id = ?",
            (dispatcher_id, now, alert_id),
        )
        conn.execute(
            "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (alert["trip_id"], alert_id, "alert_claimed", json.dumps({"dispatcher_id": dispatcher_id}), now),
        )
    updated = get_alert(alert_id)
    await manager.broadcast("alert_claimed", updated)
    await manager.broadcast("snapshot", snapshot())
    return updated


@app.get("/alerts")
def list_alerts() -> list[dict]:
    with connect() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall())
    return [hydrate_alert(row) for row in rows]


@app.get("/alerts/{alert_id}")
def get_alert(alert_id: str) -> dict:
    with connect() as conn:
        alert = row_to_dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        trip = row_to_dict(conn.execute("SELECT destination_name, route_name FROM trips WHERE id = ?", (alert["trip_id"],)).fetchone())
        rider = row_to_dict(
            conn.execute(
                "SELECT riders.name, riders.phone FROM riders JOIN trips ON trips.rider_id = riders.id WHERE trips.id = ?",
                (alert["trip_id"],),
            ).fetchone()
        )
    return {**hydrate_alert(alert), "trip": trip, "rider": rider}


@app.post("/alerts/{alert_id}/escalate")
async def escalate_alert(alert_id: str) -> dict:
    with connect() as conn:
        alert = row_to_dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
        if not alert or alert["status"] == "claimed":
            return alert or {}
        next_tier = min(int(alert["tier"]) + 1, 3)
        status = "critical" if next_tier == 3 else "open"
        severity = "red" if next_tier >= 2 else alert["severity"]
        now = utc_now()
        conn.execute(
            "UPDATE alerts SET tier = ?, status = ?, severity = ?, assigned_dispatcher_id = NULL, updated_at = ? WHERE id = ?",
            (next_tier, status, severity, now, alert_id),
        )
        conn.execute(
            "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (alert["trip_id"], alert_id, "alert_escalated", json.dumps({"tier": next_tier}), now),
        )
    updated = get_alert(alert_id)
    await manager.broadcast("alert_escalated", updated)
    await manager.broadcast("snapshot", snapshot())
    return updated


@app.post("/demo/reset")
async def reset_demo() -> dict:
    with connect() as conn:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM alerts")
        conn.execute("DELETE FROM locations")
        conn.execute("DELETE FROM trips")
        conn.execute("UPDATE dispatchers SET on_duty = 1")
    await manager.broadcast("snapshot", snapshot())
    return {"ok": True}


@app.post("/demo/run/{scenario}")
async def run_demo_scenario(scenario: str = "wrong-bus") -> dict:
    trip = await create_trip(CreateTripRequest())
    trace = WRONG_BUS_TRACE if scenario == "wrong-bus" else ON_ROUTE_TRACE
    for lat, lon in trace:
        await add_location(trip["id"], LocationRequest(lat=lat, lon=lon, source=f"demo:{scenario}"))
    return get_trip(trip["id"])
