from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

DB_PATH = Path(__file__).resolve().parents[2] / "guardian.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                service_area TEXT NOT NULL,
                emergency_phone TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS riders (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                preferred_language TEXT NOT NULL,
                phone TEXT NOT NULL,
                permissions_json TEXT NOT NULL,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            );

            CREATE TABLE IF NOT EXISTS dispatchers (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                languages TEXT NOT NULL,
                phone TEXT NOT NULL,
                on_duty INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            );

            CREATE TABLE IF NOT EXISTS trips (
                id TEXT PRIMARY KEY,
                rider_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                destination_name TEXT NOT NULL,
                route_id TEXT NOT NULL,
                route_name TEXT NOT NULL,
                status TEXT NOT NULL,
                severity TEXT NOT NULL,
                route_shape_json TEXT NOT NULL,
                milestones_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (rider_id) REFERENCES riders(id),
                FOREIGN KEY (organization_id) REFERENCES organizations(id)
            );

            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                source TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips(id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                trip_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                deviation_type TEXT NOT NULL,
                tier INTEGER NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                assigned_dispatcher_id TEXT,
                triage_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips(id),
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (assigned_dispatcher_id) REFERENCES dispatchers(id)
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trip_id TEXT,
                alert_id TEXT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips(id),
                FOREIGN KEY (alert_id) REFERENCES alerts(id)
            );
            """
        )
        seed(conn)


def seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO organizations VALUES (?, ?, ?, ?)",
        ("org_vacc", "Vietnamese American Community Center", "Westminster, CA", "+17145550111"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO riders VALUES (?, ?, ?, ?, ?, ?)",
        (
            "rider_nguyen",
            "org_vacc",
            "Mr. Nguyen",
            "vi",
            "+17145550123",
            json.dumps({"location": True, "notifications": True, "microphone": True}),
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO dispatchers VALUES (?, ?, ?, ?, ?, ?)",
        (
            "dispatcher_lan",
            "org_vacc",
            "Lan Tran",
            "Vietnamese, English",
            "+17145550199",
            1,
        ),
    )


def log_event(trip_id: str | None, alert_id: str | None, event_type: str, payload: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO events (trip_id, alert_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (trip_id, alert_id, event_type, json.dumps(payload), utc_now()),
        )


def hydrate_trip(row: dict) -> dict:
    row["route_shape"] = json.loads(row.pop("route_shape_json"))
    row["milestones"] = json.loads(row.pop("milestones_json"))
    return row


def hydrate_alert(row: dict) -> dict:
    row["triage"] = json.loads(row.pop("triage_json"))
    return row
