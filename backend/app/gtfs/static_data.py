from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from math import atan2, cos, radians, sin, sqrt


@dataclass(frozen=True)
class Stop:
    id: str
    name: str
    lat: float
    lon: float
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class DemoRoute:
    id: str
    name: str
    description: str
    stops: tuple[Stop, ...]
    shape: tuple[tuple[float, float], ...]


WESTMINSTER_CLINIC = Stop(
    id="stop_westminster_clinic",
    name="Westminster Clinic",
    lat=33.7596,
    lon=-117.9892,
    aliases=("phong kham westminster", "clinic", "westminster medical clinic"),
)

DEMO_ROUTE = DemoRoute(
    id="oc43",
    name="OC Bus Route 43",
    description="Demo route from Bolsa / Magnolia to Westminster Clinic.",
    stops=(
        Stop("stop_bolsa_magnolia", "Bolsa Ave and Magnolia St", 33.7444, -117.9726),
        Stop("stop_bolsa_brookhurst", "Bolsa Ave and Brookhurst St", 33.7449, -117.9544),
        Stop("stop_westminster_mall", "Westminster Mall Transit Center", 33.7469, -117.9912),
        WESTMINSTER_CLINIC,
    ),
    shape=(
        (33.7444, -117.9726),
        (33.7449, -117.9544),
        (33.7490, -117.9650),
        (33.7534, -117.9781),
        (33.7596, -117.9892),
    ),
)

LANDMARKS: tuple[Stop, ...] = (
    WESTMINSTER_CLINIC,
    Stop(
        "stop_vietnamese_community_center",
        "Vietnamese American Community Center",
        33.7446,
        -117.9700,
        ("vietnamese center", "community center", "trung tam cong dong"),
    ),
)

WRONG_BUS_TRACE = (
    (33.7444, -117.9726),
    (33.7485, -117.9750),
    (33.7546, -117.9782),
    (33.7625, -117.9799),
    (33.7720, -117.9828),
)

ON_ROUTE_TRACE = DEMO_ROUTE.shape


def haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    earth_radius_m = 6_371_000
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    value = sin(d_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    return 2 * earth_radius_m * atan2(sqrt(value), sqrt(1 - value))


def min_distance_to_shape_meters(point: tuple[float, float], shape: tuple[tuple[float, float], ...]) -> float:
    return min(haversine_meters(point, route_point) for route_point in shape)


def destination_candidates(query: str, limit: int = 3) -> list[dict]:
    normalized = query.strip().lower()
    candidates: list[dict] = []
    for stop in (*DEMO_ROUTE.stops, *LANDMARKS):
        names = (stop.name.lower(), *(alias.lower() for alias in stop.aliases))
        score = max(SequenceMatcher(None, normalized, name).ratio() for name in names)
        if normalized and any(normalized in name for name in names):
            score = max(score, 0.92)
        candidates.append(
            {
                "id": stop.id,
                "name": stop.name,
                "lat": stop.lat,
                "lon": stop.lon,
                "score": round(score, 3),
            }
        )
    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:limit]


def remaining_stops(point: tuple[float, float]) -> int:
    distances = [haversine_meters(point, route_point) for route_point in DEMO_ROUTE.shape]
    index = min(range(len(distances)), key=distances.__getitem__)
    return max(len(DEMO_ROUTE.shape) - 1 - index, 0)


def journey_milestones(route_name: str, locations: list[dict], destination: Stop = WESTMINSTER_CLINIC) -> list[dict]:
    boarded = len(locations) >= 1
    approaching = False
    arrived = False
    if locations:
        latest = locations[-1]
        distance = haversine_meters((float(latest["lat"]), float(latest["lon"])), (destination.lat, destination.lon))
        approaching = distance < 800
        arrived = distance < 80
    return [
        {"label": "Trip confirmed", "complete": True},
        {"label": f"Board {route_name}", "complete": boarded},
        {"label": f"Approaching {destination.name}", "complete": approaching},
        {"label": "Arrived", "complete": arrived},
    ]


def resolve_destination(query: str) -> dict:
    candidates = destination_candidates(query)
    best = candidates[0] if candidates else {
        "id": WESTMINSTER_CLINIC.id,
        "name": WESTMINSTER_CLINIC.name,
        "lat": WESTMINSTER_CLINIC.lat,
        "lon": WESTMINSTER_CLINIC.lon,
        "score": 0,
    }
    return {
        "destination": best,
        "candidates": candidates,
        "route": {
            "id": DEMO_ROUTE.id,
            "name": DEMO_ROUTE.name,
            "description": DEMO_ROUTE.description,
            "stops": [stop.__dict__ for stop in DEMO_ROUTE.stops],
            "shape": DEMO_ROUTE.shape,
        },
        "spoken_confirmation": f"You will take {DEMO_ROUTE.name}. The bus leaves soon from your current stop.",
    }
