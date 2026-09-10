# Demo GTFS Data

The hackathon MVP ships with a small in-code demo route for reliability:

- `OC Bus Route 43`
- `Bolsa Ave and Magnolia St`
- `Westminster Mall Transit Center`
- `Westminster Clinic`

Drop real GTFS static files in this folder when available:

- `stops.txt`
- `routes.txt`
- `trips.txt`
- `stop_times.txt`
- `shapes.txt`

The current implementation uses `backend/app/gtfs/static_data.py` so the live demo works without external feeds.
