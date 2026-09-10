from __future__ import annotations

import json
import time
import urllib.request

API = "http://localhost:8000"


def post(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        f"{API}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    trip = post("/trips", {"rider_id": "rider_nguyen", "destination": "Westminster Clinic", "mode": "demo-script"})
    trace = [
        (33.7444, -117.9726),
        (33.7485, -117.9750),
        (33.7546, -117.9782),
        (33.7625, -117.9799),
        (33.7720, -117.9828),
    ]
    for lat, lon in trace:
        result = post(f"/trips/{trip['id']}/locations", {"lat": lat, "lon": lon, "source": "script"})
        print(result["compliance"])
        time.sleep(0.5)


if __name__ == "__main__":
    main()
