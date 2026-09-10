import { ReactNode, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Bell, CheckCircle2, MapPin, Mic, Phone, Play, Radio, Shield, Users } from "lucide-react";
import { MapContainer, Marker, Polyline, TileLayer } from "react-leaflet";
import { Alert, api, Dispatcher, Snapshot, Trip, WS_BASE } from "./api";

const initialSnapshot: Snapshot = { riders: [], dispatchers: [], trips: [], alerts: [] };

export function App() {
  const [snapshot, setSnapshot] = useState<Snapshot>(initialSnapshot);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.snapshot().then(setSnapshot).catch((err) => setError(err.message));
    const socket = new WebSocket(`${WS_BASE}/ws`);
    socket.onmessage = (message) => {
      const data = JSON.parse(message.data);
      if (data.event === "snapshot") {
        setSnapshot(data.payload);
      } else {
        api.snapshot().then(setSnapshot).catch(() => undefined);
      }
    };
    return () => socket.close();
  }, []);

  const path = window.location.pathname;
  return (
    <main>
      <nav className="topbar">
        <a className="brand" href="/dispatcher"><Shield size={22} /> Guardian</a>
        <div>
          <a href="/rider">Rider</a>
          <a href="/dispatcher">Dispatcher</a>
          <a href="/admin">Admin</a>
          <a href="/demo">Demo</a>
        </div>
      </nav>
      {error && <div className="banner danger">API error: {error}</div>}
      {path.startsWith("/rider") ? <RiderInterface snapshot={snapshot} refresh={setSnapshot} /> : null}
      {path.startsWith("/admin") ? <AdminView snapshot={snapshot} refresh={setSnapshot} /> : null}
      {path.startsWith("/demo") ? <DemoView refresh={setSnapshot} /> : null}
      {!path.startsWith("/rider") && !path.startsWith("/admin") && !path.startsWith("/demo") ? (
        <DispatcherDashboard snapshot={snapshot} refresh={setSnapshot} />
      ) : null}
    </main>
  );
}

function RiderInterface({ snapshot, refresh }: { snapshot: Snapshot; refresh: (snapshot: Snapshot) => void }) {
  const rider = snapshot.riders[0];
  const [destination, setDestination] = useState("Westminster Clinic");
  const [listening, setListening] = useState(false);
  const [message, setMessage] = useState("Tap the button and say where you want to go.");
  const [permissions, setPermissions] = useState<Record<string, boolean>>({ location: true, notifications: true, microphone: true });

  useEffect(() => {
    if (rider?.permissions) setPermissions(rider.permissions);
  }, [rider]);

  async function startTrip() {
    try {
      await api.updatePermissions(permissions);
      const trip = await api.createTrip(destination);
      speak(`Confirmed. ${trip.resolution?.spoken_confirmation ?? "Guardian is watching your trip."}`);
      setMessage("Trip active. Guardian is watching silently.");
      refresh(await api.snapshot());
    } catch (err) {
      setMessage("Trip blocked. Please check required permissions.");
    }
  }

  function listenForDestination() {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setMessage("Voice input is not available in this browser. Type the destination instead.");
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = rider?.preferred_language === "vi" ? "vi-VN" : "en-US";
    recognition.onstart = () => setListening(true);
    recognition.onend = () => setListening(false);
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      setDestination(transcript);
      setMessage(`Heard: ${transcript}`);
    };
    recognition.start();
  }

  return (
    <section className="rider-shell">
      <div className="hero-card">
        <p className="eyebrow">Rider Mode</p>
        <h1>Hello {rider?.name ?? "rider"}</h1>
        <p>{message}</p>
        <button className={`voice-button ${listening ? "pulse" : ""}`} onClick={listenForDestination}>
          <Mic size={42} />
          Speak Destination
        </button>
        <input value={destination} onChange={(event) => setDestination(event.target.value)} aria-label="Destination" />
        <button className="primary large" onClick={startTrip}>Start Guardian Trip</button>
      </div>
      <div className="card">
        <h2>Permissions Checklist</h2>
        {(["location", "notifications", "microphone"] as const).map((key) => (
          <label className="check-row" key={key}>
            <input type="checkbox" checked={permissions[key]} onChange={(event) => setPermissions({ ...permissions, [key]: event.target.checked })} />
            <span>{permissionLabel(key)}</span>
          </label>
        ))}
        <p className="muted">Location, notifications, and audio must be enabled before Guardian can supervise a trip.</p>
      </div>
    </section>
  );
}

function DispatcherDashboard({ snapshot, refresh }: { snapshot: Snapshot; refresh: (snapshot: Snapshot) => void }) {
  const selectedTrip = snapshot.trips[0];
  const activeAlerts = snapshot.alerts.filter((alert) => alert.status !== "resolved");

  async function claim(alert: Alert) {
    await api.claimAlert(alert.id);
    refresh(await api.snapshot());
    speak(alert.triage.rider_phrase);
  }

  return (
    <section className="dashboard-grid">
      <div className="column">
        <PanelTitle icon={<Radio />} title="Live Trip Feed" />
        {snapshot.trips.length === 0 ? <EmptyState text="No active trips. Start one from Rider or Demo mode." /> : null}
        {snapshot.trips.map((trip) => <TripCard key={trip.id} trip={trip} />)}
      </div>
      <div className="column">
        <PanelTitle icon={<Bell />} title="Alert Queue" />
        {activeAlerts.length === 0 ? <EmptyState text="No alerts. All monitored trips are green." /> : null}
        {activeAlerts.map((alert) => (
          <article className={`card alert ${alert.severity}`} key={alert.id}>
            <div className="row between">
              <strong>Tier {alert.tier}: {alert.deviation_type.split("_").join(" ")}</strong>
              <span className="pill">{alert.status}</span>
            </div>
            <p>{alert.triage.summary}</p>
            <p className="muted">{alert.triage.recommended_action}</p>
            <div className="actions">
              <button className="primary" onClick={() => claim(alert)}>Claim Alert</button>
              <a className="button" href={`tel:${alert.rider?.phone ?? "+17145550123"}`}><Phone size={16} /> Call Rider</a>
              <button className="ghost" onClick={async () => { await api.escalateAlert(alert.id); refresh(await api.snapshot()); }}>Escalate</button>
            </div>
          </article>
        ))}
      </div>
      <div className="column wide">
        <PanelTitle icon={<MapPin />} title="Route Map" />
        <RouteMap trip={selectedTrip} />
        {selectedTrip ? <Timeline trip={selectedTrip} /> : null}
      </div>
    </section>
  );
}

function AdminView({ snapshot, refresh }: { snapshot: Snapshot; refresh: (snapshot: Snapshot) => void }) {
  async function toggle(dispatcher: Dispatcher) {
    await api.setDuty(dispatcher.id, !dispatcher.on_duty);
    refresh(await api.snapshot());
  }
  return (
    <section className="content">
      <PanelTitle icon={<Users />} title="Organization Admin" />
      <div className="grid two">
        {snapshot.dispatchers.map((dispatcher) => (
          <article className="card" key={dispatcher.id}>
            <h2>{dispatcher.name}</h2>
            <p>{dispatcher.languages}</p>
            <p className="muted">{dispatcher.phone}</p>
            <button className={dispatcher.on_duty ? "primary" : "ghost"} onClick={() => toggle(dispatcher)}>
              {dispatcher.on_duty ? "On Duty" : "Off Duty"}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}

function DemoView({ refresh }: { refresh: (snapshot: Snapshot) => void }) {
  const [status, setStatus] = useState("Ready to replay the Mr. Nguyen scenario.");
  async function run(scenario: string) {
    setStatus(`Running ${scenario} simulation...`);
    await api.runDemo(scenario);
    refresh(await api.snapshot());
    setStatus("Simulation complete. Open Dispatcher to see the alert flow.");
  }
  async function reset() {
    await api.resetDemo();
    refresh(await api.snapshot());
    setStatus("Demo data reset.");
  }
  return (
    <section className="content">
      <PanelTitle icon={<Play />} title="Judge Demo Controls" />
      <div className="card">
        <h1>Mr. Nguyen to Westminster Clinic</h1>
        <p>{status}</p>
        <div className="actions">
          <button className="primary" onClick={() => run("wrong-bus")}>Run Wrong-Bus Demo</button>
          <button className="ghost" onClick={() => run("on-route")}>Run On-Route Demo</button>
          <button className="ghost" onClick={reset}>Reset Demo</button>
        </div>
      </div>
    </section>
  );
}

function TripCard({ trip }: { trip: Trip }) {
  return (
    <article className={`card trip ${trip.severity}`}>
      <div className="row between">
        <strong>{trip.rider?.name ?? "Mr. Nguyen"}</strong>
        <span className="pill">{trip.status}</span>
      </div>
      <p>{trip.route_name} to {trip.destination_name}</p>
      <p className="muted">{trip.locations?.length ?? 0} GPS pings received</p>
    </article>
  );
}

function RouteMap({ trip }: { trip?: Trip }) {
  const center = useMemo<[number, number]>(() => trip?.route_shape?.[0] ?? [33.7444, -117.9726], [trip]);
  const latest = trip?.locations?.[trip.locations.length - 1];
  return (
    <div className="map-card">
      <MapContainer center={center} zoom={13} scrollWheelZoom={false} className="map">
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {trip?.route_shape ? <Polyline positions={trip.route_shape} pathOptions={{ color: "#2563eb", weight: 5 }} /> : null}
        {latest ? <Marker position={[latest.lat, latest.lon]} /> : null}
      </MapContainer>
    </div>
  );
}

function Timeline({ trip }: { trip: Trip }) {
  return (
    <div className="card">
      <h2>Journey Milestones</h2>
      {trip.milestones.map((milestone) => (
        <div className="timeline-row" key={milestone.label}>
          {milestone.complete ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
          <span>{milestone.label}</span>
        </div>
      ))}
    </div>
  );
}

function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return <h1 className="panel-title">{icon}{title}</h1>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="card muted">{text}</div>;
}

function permissionLabel(key: string) {
  const labels: Record<string, string> = {
    location: "Location always on: lets Guardian watch the trip.",
    notifications: "Notifications: lets Guardian alert you in the background.",
    microphone: "Microphone/audio: lets Guardian hear and speak confirmations.",
  };
  return labels[key];
}

function speak(text: string) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}
