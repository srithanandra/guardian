from __future__ import annotations

from datetime import datetime, timezone

from backend.app.gtfs.static_data import DEMO_ROUTE, haversine_meters, min_distance_to_shape_meters

CORRIDOR_METERS = 500
CRITICAL_CORRIDOR_METERS = 805
STATIONARY_METERS = 20
STATIONARY_SECONDS = 30 * 60


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _progress_index(point: tuple[float, float]) -> int:
    distances = [haversine_meters(point, route_point) for route_point in DEMO_ROUTE.shape]
    return min(range(len(distances)), key=distances.__getitem__)


def evaluate_route_compliance(locations: list[dict], route_shape: tuple[tuple[float, float], ...] = DEMO_ROUTE.shape) -> dict:
    if not locations:
        return {"status": "pending", "deviation_type": None, "severity": "green", "message": "Waiting for first GPS point."}

    latest = locations[-1]
    point = (float(latest["lat"]), float(latest["lon"]))
    distance = min_distance_to_shape_meters(point, route_shape)

    if len(locations) >= 2:
        previous = locations[-2]
        previous_point = (float(previous["lat"]), float(previous["lon"]))
        reversed_direction = _progress_index(point) + 1 < _progress_index(previous_point)
    else:
        reversed_direction = False

    if len(locations) >= 3:
        first_recent = locations[-3]
        first_point = (float(first_recent["lat"]), float(first_recent["lon"]))
        movement = haversine_meters(first_point, point)
        elapsed = (_parse_time(latest.get("recorded_at")) - _parse_time(first_recent.get("recorded_at"))).total_seconds()
    else:
        movement = 999
        elapsed = 0

    if distance > CRITICAL_CORRIDOR_METERS:
        return {
            "status": "critical",
            "deviation_type": "outside_corridor",
            "severity": "red",
            "message": "Rider is outside the route corridor.",
            "distance_from_route_m": round(distance),
        }

    if distance > CORRIDOR_METERS:
        return {
            "status": "deviating",
            "deviation_type": "wrong_bus",
            "severity": "red",
            "message": "Rider appears to be traveling away from the planned route.",
            "distance_from_route_m": round(distance),
        }

    if reversed_direction:
        return {
            "status": "deviating",
            "deviation_type": "wrong_direction",
            "severity": "yellow",
            "message": "Rider appears to be moving opposite the planned route direction.",
            "distance_from_route_m": round(distance),
        }

    if movement <= STATIONARY_METERS and elapsed >= STATIONARY_SECONDS:
        return {
            "status": "deviating",
            "deviation_type": "stationary_too_long",
            "severity": "yellow",
            "message": "Rider has been stationary longer than expected.",
            "distance_from_route_m": round(distance),
        }

    return {
        "status": "on_track",
        "deviation_type": None,
        "severity": "green",
        "message": "Rider is within the expected route corridor.",
        "distance_from_route_m": round(distance),
    }
