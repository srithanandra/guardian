from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.app.agents.escort_scripts import spoken_instruction
from backend.app.agents.route_compliance import evaluate_route_compliance
from backend.app.agents.triage import generate_triage
from backend.app.db import connect, hydrate_alert, hydrate_trip, init_db, row_to_dict, rows_to_dicts, utc_now
from backend.app.gtfs.static_data import (
    ON_ROUTE_TRACE,
    WRONG_BUS_TRACE,
    journey_milestones,
    remaining_stops,
    resolve_destination,
)

TIER_HOLD_SECONDS = float(os.getenv("GUARDIAN_TIER_HOLD_SECONDS", "8"))
DEMO_PING_SECONDS = float(os.getenv("GUARDIAN_DEMO_PING_SECONDS", "1.2"))
DEMO_SYNC = os.getenv("GUARDIAN_DEMO_SYNC", "").lower() in {"1", "true", "yes"}
AUTO_ESCALATE = os.getenv("GUARDIAN_AUTO_ESCALATE", "1").lower() not in {"0", "false", "no"}
JUDGE_TRACE = ON_ROUTE_TRACE[:3] + WRONG_BUS_TRACE[2:]
ESCORT_BY_TIER = {1: "tier1_redirect", 2: "tier2_checkin", 3: "tier3_dispatch"}

app = FastAPI(title="Guardian API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

escalation_tasks: dict[str, asyncio.Task] = {}
demo_tasks: list[asyncio.Task] = []


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
        instruction = spoken_instruction(
            "on_track",
            rider.get("preferred_language"),
            destination=resolution["destination"]["name"],
        )
        milestones = journey_milestones(resolution["route"]["name"], [])
        now = utc_now()
        conn.execute(
            """
            INSERT INTO trips (
                id, rider_id, organization_id, destination_name, route_id, route_name,
                status, severity, route_shape_json, milestones_json, created_at, updated_at,
                escort_state, spoken_instruction, companion_notified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                "on_track",
                instruction,
                0,
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
        rows = rows_to_dicts(conn.execute("SELECT id FROM trips ORDER BY created_at DESC").fetchall())
    return [get_trip(row["id"]) for row in rows]


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
        rider = row_to_dict(
            conn.execute(
                "SELECT name, preferred_language, phone, care_notes, companion_name, companion_phone FROM riders WHERE id = ?",
                (trip["rider_id"],),
            ).fetchone()
        )
    return {
        **hydrate_trip(trip),
        "rider": rider,
        "locations": locations,
        "alerts": [enrich_alert(hydrate_alert(alert)) for alert in alerts],
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
        rider = row_to_dict(conn.execute("SELECT preferred_language FROM riders WHERE id = ?", (trip["rider_id"],)).fetchone())

    route_shape = tuple(tuple(point) for point in json.loads(trip["route_shape_json"]))
    compliance = evaluate_route_compliance(locations, route_shape)
    await apply_location_progress(trip, rider, locations, compliance)
    if compliance["deviation_type"] and trip.get("escort_state") == "on_track":
        await create_alert_if_needed(trip_id, compliance)

    hydrated = get_trip(trip_id)
    await manager.broadcast("location_added", {"trip": hydrated, "compliance": compliance})
    await manager.broadcast("snapshot", snapshot())
    return {"trip": hydrated, "compliance": compliance}


@app.post("/trips/{trip_id}/help")
async def request_help(trip_id: str) -> dict:
    with connect() as conn:
        trip = row_to_dict(conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone())
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        alert = row_to_dict(
            conn.execute(
                "SELECT * FROM alerts WHERE trip_id = ? AND status IN ('open', 'claimed', 'critical') ORDER BY created_at DESC",
                (trip_id,),
            ).fetchone()
        )

    if alert:
        cancel_escalation(alert["id"])
        await set_escort_tier(trip_id, alert["id"], 3, help_requested=True)
    else:
        compliance = {
            "status": "critical",
            "deviation_type": "help_requested",
            "severity": "red",
            "message": "Rider pressed Help.",
            "distance_from_route_m": 0,
        }
        alert = await create_alert_if_needed(trip_id, compliance, tier=3, help_requested=True)
        if alert:
            cancel_escalation(alert["id"])

    hydrated = get_trip(trip_id)
    await manager.broadcast("help_requested", hydrated)
    await manager.broadcast("snapshot", snapshot())
    return hydrated


async def apply_location_progress(trip: dict, rider: dict | None, locations: list[dict], compliance: dict) -> None:
    latest = locations[-1]
    point = (float(latest["lat"]), float(latest["lon"]))
    milestones = journey_milestones(trip["route_name"], locations)
    arrived = bool(milestones[-1]["complete"])
    escort_state = trip.get("escort_state") or "on_track"
    instruction = trip.get("spoken_instruction") or ""
    if escort_state == "on_track":
        instruction = spoken_instruction(
            "on_track",
            (rider or {}).get("preferred_language"),
            destination=trip["destination_name"],
            stops_remaining=remaining_stops(point),
            arrived=arrived,
        )
    with connect() as conn:
        conn.execute(
            """
            UPDATE trips
            SET status = ?, severity = ?, milestones_json = ?, spoken_instruction = ?, updated_at = ?
            WHERE id = ?
            """,
            (compliance["status"], compliance["severity"], json.dumps(milestones), instruction, utc_now(), trip["id"]),
        )


async def create_alert_if_needed(
    trip_id: str,
    compliance: dict,
    tier: int = 1,
    help_requested: bool = False,
) -> dict | None:
    with connect() as conn:
        existing = row_to_dict(
            conn.execute(
                "SELECT * FROM alerts WHERE trip_id = ? AND status IN ('open', 'claimed', 'critical')",
                (trip_id,),
            ).fetchone()
        )
        if existing:
            return hydrate_alert(existing)
        trip = row_to_dict(conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone())
        rider = row_to_dict(conn.execute("SELECT * FROM riders WHERE id = ?", (trip["rider_id"],)).fetchone())
        dispatcher = row_to_dict(
            conn.execute(
                "SELECT id FROM dispatchers WHERE organization_id = ? AND on_duty = 1 ORDER BY name LIMIT 1",
                (trip["organization_id"],),
            ).fetchone()
        )
        locations = rows_to_dicts(
            conn.execute("SELECT lat, lon, source, recorded_at FROM locations WHERE trip_id = ? ORDER BY id", (trip_id,)).fetchall()
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
        escort_state = ESCORT_BY_TIER[tier]
        instruction = spoken_instruction(
            escort_state,
            rider.get("preferred_language"),
            destination=trip["destination_name"],
            help_requested=help_requested,
        )
        status = "critical" if tier >= 3 else "open"
        severity = "red" if tier >= 2 or compliance.get("severity") == "red" else compliance.get("severity", "yellow")
        conn.execute(
            """
            INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                trip_id,
                trip["organization_id"],
                compliance["deviation_type"],
                tier,
                severity,
                status,
                dispatcher["id"] if dispatcher else None,
                json.dumps(triage),
                now,
                now,
            ),
        )
        conn.execute(
            """
            UPDATE trips
            SET escort_state = ?, spoken_instruction = ?, companion_notified = ?, status = ?, severity = ?, updated_at = ?
            WHERE id = ?
            """,
            (escort_state, instruction, 1 if tier >= 2 else 0, compliance.get("status", "deviating"), severity, now, trip_id),
        )
        org = row_to_dict(conn.execute("SELECT name, emergency_phone FROM organizations WHERE id = ?", (trip["organization_id"],)).fetchone())
        payload = build_payload(trip, rider, locations, org)
        conn.execute(
            "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, alert_id, "alert_created", json.dumps({**event, "tier": tier, **payload}), now),
        )
        if tier >= 2:
            conn.execute(
                "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    trip_id,
                    alert_id,
                    "companion_notified",
                    json.dumps({"companion_name": rider.get("companion_name"), "companion_phone": rider.get("companion_phone"), "mocked": True}),
                    now,
                ),
            )
    created = get_alert(alert_id)
    await manager.broadcast("alert_created", created)
    if tier < 3 and AUTO_ESCALATE:
        schedule_escalation(alert_id)
    return created


def cancel_escalation(alert_id: str) -> None:
    task = escalation_tasks.pop(alert_id, None)
    if task:
        task.cancel()


def cancel_all_background() -> None:
    for alert_id in list(escalation_tasks):
        cancel_escalation(alert_id)
    for task in demo_tasks:
        task.cancel()
    demo_tasks.clear()


def schedule_escalation(alert_id: str) -> None:
    cancel_escalation(alert_id)
    escalation_tasks[alert_id] = asyncio.create_task(_auto_escalate(alert_id))


async def _auto_escalate(alert_id: str) -> None:
    try:
        await asyncio.sleep(TIER_HOLD_SECONDS)
        updated = await escalate_alert(alert_id)
        if updated and updated.get("status") != "claimed" and int(updated.get("tier") or 3) < 3:
            schedule_escalation(alert_id)
    except asyncio.CancelledError:
        return


async def set_escort_tier(trip_id: str, alert_id: str, tier: int, help_requested: bool = False) -> dict:
    with connect() as conn:
        trip = row_to_dict(conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone())
        rider = row_to_dict(conn.execute("SELECT * FROM riders WHERE id = ?", (trip["rider_id"],)).fetchone())
        locations = rows_to_dicts(
            conn.execute("SELECT lat, lon, source, recorded_at FROM locations WHERE trip_id = ? ORDER BY id", (trip_id,)).fetchall()
        )
        escort_state = ESCORT_BY_TIER[tier]
        instruction = spoken_instruction(
            escort_state,
            rider.get("preferred_language"),
            destination=trip["destination_name"],
            help_requested=help_requested,
        )
        now = utc_now()
        status = "critical" if tier >= 3 else "open"
        severity = "red" if tier >= 2 else "yellow"
        notify = 1 if tier >= 2 or help_requested else 0
        conn.execute(
            "UPDATE alerts SET tier = ?, status = ?, severity = ?, assigned_dispatcher_id = NULL, updated_at = ? WHERE id = ?",
            (tier, status, severity, now, alert_id),
        )
        conn.execute(
            """
            UPDATE trips
            SET escort_state = ?, spoken_instruction = ?, companion_notified = ?, status = ?, severity = ?, updated_at = ?
            WHERE id = ?
            """,
            (escort_state, instruction, notify, "critical" if tier >= 3 else "deviating", severity, now, trip_id),
        )
        org = row_to_dict(conn.execute("SELECT name, emergency_phone FROM organizations WHERE id = ?", (trip["organization_id"],)).fetchone())
        event_type = "help_requested" if help_requested else "alert_escalated"
        conn.execute(
            "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, alert_id, event_type, json.dumps({"tier": tier, **build_payload(trip, rider, locations, org)}), now),
        )
        if notify and not trip.get("companion_notified"):
            conn.execute(
                "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    trip_id,
                    alert_id,
                    "companion_notified",
                    json.dumps({"companion_name": rider.get("companion_name"), "companion_phone": rider.get("companion_phone"), "mocked": True}),
                    now,
                ),
            )
    return get_alert(alert_id)


def build_payload(trip: dict, rider: dict, locations: list[dict], org: dict | None = None) -> dict:
    latest = locations[-1] if locations else None
    return {
        "rider_name": rider.get("name"),
        "last_known_location": {"lat": latest["lat"], "lon": latest["lon"]} if latest else None,
        "destination": trip.get("destination_name"),
        "care_notes": rider.get("care_notes") or "",
        "companion_name": rider.get("companion_name") or "",
        "companion_phone": rider.get("companion_phone") or "",
        "organization_name": (org or {}).get("name"),
        "organization_phone": (org or {}).get("emergency_phone"),
        "mocked": True,
    }


def enrich_alert(alert: dict) -> dict:
    with connect() as conn:
        trip = row_to_dict(conn.execute("SELECT * FROM trips WHERE id = ?", (alert["trip_id"],)).fetchone())
        if not trip:
            return alert
        rider = row_to_dict(conn.execute("SELECT * FROM riders WHERE id = ?", (trip["rider_id"],)).fetchone())
        locations = rows_to_dicts(
            conn.execute("SELECT lat, lon, source, recorded_at FROM locations WHERE trip_id = ? ORDER BY id", (alert["trip_id"],)).fetchall()
        )
        org = row_to_dict(conn.execute("SELECT name, emergency_phone FROM organizations WHERE id = ?", (trip["organization_id"],)).fetchone())
    payload = build_payload(trip, rider or {}, locations, org)
    return {
        **alert,
        "trip": {"destination_name": trip["destination_name"], "route_name": trip["route_name"]},
        "rider": {"name": (rider or {}).get("name"), "phone": (rider or {}).get("phone")},
        "organization": org,
        "companion_notified": bool(trip.get("companion_notified")),
        "escalation_payload": payload,
    }


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
    cancel_escalation(alert_id)
    updated = get_alert(alert_id)
    await manager.broadcast("alert_claimed", updated)
    await manager.broadcast("snapshot", snapshot())
    return updated


@app.get("/alerts")
def list_alerts() -> list[dict]:
    with connect() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall())
    return [enrich_alert(hydrate_alert(row)) for row in rows]


@app.get("/alerts/{alert_id}")
def get_alert(alert_id: str) -> dict:
    with connect() as conn:
        alert = row_to_dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
    return enrich_alert(hydrate_alert(alert))


@app.post("/alerts/{alert_id}/escalate")
async def escalate_alert(alert_id: str) -> dict:
    with connect() as conn:
        alert = row_to_dict(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone())
        if not alert:
            return {}
        if alert["status"] == "claimed":
            return get_alert(alert_id)
        next_tier = min(int(alert["tier"]) + 1, 3)
        if next_tier == int(alert["tier"]):
            return get_alert(alert_id)
    updated = await set_escort_tier(alert["trip_id"], alert_id, next_tier)
    await manager.broadcast("alert_escalated", updated)
    await manager.broadcast("snapshot", snapshot())
    return updated


@app.post("/demo/reset")
async def reset_demo() -> dict:
    cancel_all_background()
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
    trip_id = active_trip_id()
    if not trip_id:
        created = await create_trip(CreateTripRequest(mode=f"demo:{scenario}"))
        trip_id = created["id"]
    if DEMO_SYNC:
        await play_demo_script(trip_id, scenario)
    else:
        task = asyncio.create_task(play_demo_script(trip_id, scenario))
        demo_tasks.append(task)
    return get_trip(trip_id)


def active_trip_id() -> str | None:
    with connect() as conn:
        row = row_to_dict(conn.execute("SELECT id FROM trips ORDER BY created_at DESC LIMIT 1").fetchone())
    return row["id"] if row else None


async def play_demo_script(trip_id: str, scenario: str) -> None:
    if scenario in {"wrong-bus", "judge", "full-script"}:
        trace = JUDGE_TRACE
        source = "demo:judge"
    else:
        trace = ON_ROUTE_TRACE
        source = f"demo:{scenario}"
    for lat, lon in trace:
        await add_location(trip_id, LocationRequest(lat=lat, lon=lon, source=source))
        if DEMO_PING_SECONDS:
            await asyncio.sleep(DEMO_PING_SECONDS)
