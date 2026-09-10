# Guardian

Guardian is a hackathon MVP for AI-powered transit supervision of vulnerable riders. It is built as a React PWA plus FastAPI backend with deterministic route monitoring, dispatcher escalation, and Claude-ready triage summaries.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
npm install
npm --prefix frontend install
npm run dev
```

Backend: `http://localhost:8000`

Frontend: `http://localhost:5173`

## Demo Flow

1. Open `/rider` and start the seeded Mr. Nguyen trip to Westminster Clinic.
2. Open `/dispatcher` and watch the active trip feed.
3. Open `/demo` and run the wrong-bus simulation.
4. The backend creates an alert, attaches a triage summary, broadcasts it to the dashboard, and exposes a one-tap call action.

## Useful Commands

```bash
npm run dev:backend
npm run dev:frontend
npm test
npm run build
python scripts/simulate_trip.py
```
