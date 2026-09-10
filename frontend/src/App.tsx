import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Bell, CheckCircle2, MapPin, Mic, Phone, PhoneCall, Play, Radio, Shield, Users } from "lucide-react";
import { MapContainer, Marker, Polyline, TileLayer } from "react-leaflet";
import { Alert, api, Dispatcher, EscalationPayload, Snapshot, Trip, WS_BASE } from "./api";
import { speak, stopSpeech, unlockSpeech } from "./speech";

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
    const unlock = () => {
      unlockSpeech();
      window.removeEventListener("pointerdown", unlock);
    };
    window.addEventListener("pointerdown", unlock);
    return () => {
      socket.close();
      window.removeEventListener("pointerdown", unlock);
    };
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
      {path.startsWith("/demo") ? <DemoView snapshot={snapshot} refresh={setSnapshot} /> : null}
      {!path.startsWith("/rider") && !path.startsWith("/admin") && !path.startsWith("/demo") ? (
        <DispatcherDashboard snapshot={snapshot} refresh={setSnapshot} />
      ) : null}
    </main>
  );
}

function RiderInterface({ snapshot, refresh }: { snapshot: Snapshot; refresh: (snapshot: Snapshot) => void }) {
  const rider = snapshot.riders[0];
  const trip = snapshot.trips.find((item) => item.rider_id === rider?.id) ?? snapshot.trips[0];
  const [destination, setDestination] = useState("Westminster Clinic");
  const [listening, setListening] = useState(false);
  const [message, setMessage] = useState("Tap the button and say where you want to go.");
  const [permissions, setPermissions] = useState<Record<string, boolean>>({ location: true, notifications: true, microphone: true });
  const lastSpoken = useRef("");

  useEffect(() => {
    if (rider?.permissions) setPermissions(rider.permissions);
  }, [rider]);

  useEffect(() => {
    const instruction = trip?.spoken_instruction;
    if (!instruction || instruction === lastSpoken.current) return;
    lastSpoken.current = instruction;
    speak(instruction, speechLang(rider?.preferred_language));
  }, [trip?.spoken_instruction, rider?.preferred_language]);

  async function startTrip() {
    try {
      await api.updatePermissions(permissions);
      const created = await api.createTrip(destination);
      const confirmation = created.spoken_instruction ?? created.resolution?.spoken_confirmation ?? "Guardian is watching your trip.";
      lastSpoken.current = confirmation;
      speak(confirmation, speechLang(rider?.preferred_language));
      setMessage(confirmation);
      refresh(await api.snapshot());
    } catch {
      setMessage("Trip blocked. Please check required permissions.");
    }
  }

  async function callHelp() {
    if (!trip) return;
    const updated = await api.requestHelp(trip.id);
    lastSpoken.current = updated.spoken_instruction ?? lastSpoken.current;
    speak(updated.spoken_instruction ?? "Stay where you are. A person is coming to help.", speechLang(rider?.preferred_language));
    refresh(await api.snapshot());
  }

  async function switchLanguage(language: string) {
    lastSpoken.current = "";
    await api.setLanguage(language);
    refresh(await api.snapshot());
  }

  function listen(onResult: (transcript: string) => void) {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setMessage("Voice input is not available in this browser. Type the destination instead.");
      return;
    }
    stopSpeech();
    const recognition = new SpeechRecognition();
    recognition.lang = speechLang(rider?.preferred_language);
    recognition.onstart = () => setListening(true);
    recognition.onend = () => setListening(false);
    recognition.onresult = (event: any) => onResult(event.results[0][0].transcript);
    recognition.start();
  }

  function listenForDestination() {
    listen((transcript) => {
      setDestination(transcript);
      setMessage(`Heard: ${transcript}`);
    });
  }

  async function listenForReply() {
    if (!trip) return;
    listen(async (transcript) => {
      const result = await api.replyToTrip(trip.id, transcript);
      lastSpoken.current = result.trip.spoken_instruction ?? lastSpoken.current;
      speak(result.trip.spoken_instruction ?? "", speechLang(rider?.preferred_language));
      refresh(await api.snapshot());
    });
  }

  async function togglePermission(key: string, enabled: boolean) {
    if (!enabled) {
      setPermissions({ ...permissions, [key]: false });
      return;
    }
    try {
      if (key === "location" && navigator.geolocation) {
        await new Promise<void>((resolve) => {
          navigator.geolocation.getCurrentPosition(
            () => resolve(),
            () => resolve(),
            { timeout: 4000, maximumAge: 60000 },
          );
        });
      }
      if (key === "notifications" && "Notification" in window) {
        await Notification.requestPermission();
      }
      if (key === "microphone") {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
      }
    } catch {
      setMessage("Live sensor unavailable. Demo GPS can still run.");
    }
    setPermissions({ ...permissions, [key]: true });
  }

  if (trip) {
    const arrived = trip.milestones.some((milestone) => milestone.label === "Arrived" && milestone.complete);
    const showHelp = !(arrived && trip.escort_state === "on_track");
    const checkIn = trip.escort_state === "tier2_checkin";
    return (
      <section className="rider-shell live">
        <div className="hero-card escort-card">
          <div className="row between">
            <p className="eyebrow">Guardian is with you</p>
            <LanguageToggle current={rider?.preferred_language} onChange={switchLanguage} />
          </div>
          <p className="escort-sentence">{trip.spoken_instruction || "Stay seated. Guardian is watching."}</p>
          {showHelp ? (
            <button className="help-button" onClick={callHelp}>
              <PhoneCall size={48} />
              Help
            </button>
          ) : (
            <p className="muted">Trip complete.</p>
          )}
          {showHelp ? (
            <button className={`answer-button ${listening ? "pulse" : ""} ${checkIn ? "emphasis" : ""}`} onClick={listenForReply}>
              <Mic size={28} />
              {checkIn ? "Answer check-in" : "Speak to Guardian"}
            </button>
          ) : null}
        </div>
      </section>
    );
  }

  return (
    <section className="rider-shell">
      <div className="hero-card">
        <div className="row between">
          <p className="eyebrow">Rider Mode</p>
          <LanguageToggle current={rider?.preferred_language} onChange={switchLanguage} />
        </div>
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
            <input
              type="checkbox"
              checked={Boolean(permissions[key])}
              onChange={(event) => togglePermission(key, event.target.checked)}
            />
            <span>{permissionLabel(key)}</span>
          </label>
        ))}
        <p className="muted">Location, notifications, and audio must be enabled before Guardian can supervise a trip. Live GPS is optional during the demo.</p>
      </div>
    </section>
  );
}

function DispatcherDashboard({ snapshot, refresh }: { snapshot: Snapshot; refresh: (snapshot: Snapshot) => void }) {
  const selectedTrip = snapshot.trips[0];
  const activeAlerts = snapshot.alerts.filter((alert) => alert.status !== "resolved");
  const companionNotified = snapshot.trips.some((trip) => trip.companion_notified) || snapshot.alerts.some((alert) => alert.companion_notified);

  async function claim(alert: Alert) {
    await api.claimAlert(alert.id);
    refresh(await api.snapshot());
    speak(alert.triage.rider_phrase);
  }

  return (
    <section className="dashboard-grid">
      <div className="column">
        <PanelTitle icon={<Radio />} title="Live Trip Feed" />
        {companionNotified ? <div className="banner warn">Setup companion notified (mocked).</div> : null}
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
            {alert.tier >= 2 ? <p className="muted">Setup companion {alert.escalation_payload?.companion_name ?? "Linh Nguyen"} notified.</p> : null}
            {alert.tier >= 3 ? <EscalationFacts payload={alert.escalation_payload} /> : null}
            <div className="actions">
              <button className="primary" onClick={() => claim(alert)}>Claim Alert</button>
              <a className="button" href={`tel:${alert.rider?.phone ?? "+17145550123"}`}><Phone size={16} /> Call Rider</a>
              {alert.tier >= 3 ? (
                <a className="button" href={`tel:${alert.escalation_payload?.organization_phone ?? "+17145550111"}`}>
                  <Phone size={16} /> Call nonprofit (mocked)
                </a>
              ) : (
                <button className="ghost" onClick={async () => { await api.escalateAlert(alert.id); refresh(await api.snapshot()); }}>Escalate</button>
              )}
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

function EscalationFacts({ payload }: { payload?: EscalationPayload }) {
  if (!payload) return null;
  const location = payload.last_known_location
    ? `${payload.last_known_location.lat.toFixed(4)}, ${payload.last_known_location.lon.toFixed(4)}`
    : "Unknown";
  return (
    <dl className="payload-list">
      <div><dt>Rider</dt><dd>{payload.rider_name}</dd></div>
      <div><dt>Location</dt><dd>{location}</dd></div>
      <div><dt>Destination</dt><dd>{payload.destination}</dd></div>
      <div><dt>Care notes</dt><dd>{payload.care_notes || "None"}</dd></div>
    </dl>
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

function DemoView({ snapshot, refresh }: { snapshot: Snapshot; refresh: (snapshot: Snapshot) => void }) {
  const trip = snapshot.trips[0];
  const [status, setStatus] = useState("Ready to replay the Mr. Nguyen scenario.");

  useEffect(() => {
    if (!trip) return;
    setStatus(`${labelEscort(trip.escort_state)}. ${trip.spoken_instruction ?? ""}`.trim());
  }, [trip]);

  async function run(scenario: string) {
    setStatus(scenario === "on-route" ? "Playing the on-route ride..." : "Playing the judge script. Watch the Rider tab.");
    await api.runDemo(scenario);
    refresh(await api.snapshot());
  }
  async function reset() {
    await api.resetDemo();
    refresh(await api.snapshot());
    setStatus("Demo data reset.");
  }
  async function say(transcript: string) {
    if (!trip) {
      setStatus("Start a trip from Rider or Play Judge Demo first.");
      return;
    }
    const result = await api.replyToTrip(trip.id, transcript);
    refresh(await api.snapshot());
    setStatus(`Rider said "${transcript}" → ${result.interpretation.intent}.`);
  }
  async function setLanguage(language: string) {
    await api.setLanguage(language);
    refresh(await api.snapshot());
  }
  return (
    <section className="content">
      <PanelTitle icon={<Play />} title="Judge Demo Controls" />
      <div className="card">
        <h1>Mr. Nguyen to Westminster Clinic</h1>
        <p>{status}</p>
        <div className="actions">
          <button className="primary" onClick={() => run("wrong-bus")}>Play Judge Demo</button>
          <button className="ghost" onClick={() => run("on-route")}>Run On-Route Demo</button>
          <button className="ghost" onClick={reset}>Reset Demo</button>
        </div>
        <p className="muted">Keep /rider open. GPS then Tier 1 → 2 → 3. Switch language without changing the route.</p>
        <div className="actions">
          <LanguageToggle current={snapshot.riders[0]?.preferred_language} onChange={setLanguage} />
          <button className="ghost" onClick={() => say("yes")}>Rider says yes</button>
          <button className="ghost" onClick={() => say("I'm lost")}>Rider says I'm lost</button>
          <button className="ghost" onClick={() => say("help")}>Rider says help</button>
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
        <span className="pill">{labelEscort(trip.escort_state) || trip.status}</span>
      </div>
      <p>{trip.route_name} to {trip.destination_name}</p>
      <p className="muted">{trip.spoken_instruction}</p>
      {trip.last_reply_intent ? <p className="muted">Rider said: {trip.last_reply_intent.replace("_", " ")}</p> : null}
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

function LanguageToggle({ current, onChange }: { current?: string; onChange: (language: string) => void }) {
  const active = current?.toLowerCase().startsWith("vi") ? "vi" : "en";
  return (
    <div className="lang-toggle">
      <button className={active === "en" ? "primary" : "ghost"} onClick={() => onChange("en")}>EN</button>
      <button className={active === "vi" ? "primary" : "ghost"} onClick={() => onChange("vi")}>VI</button>
    </div>
  );
}

function permissionLabel(key: string) {
  const labels: Record<string, string> = {
    location: "Location always on: lets Guardian watch the trip.",
    notifications: "Notifications: lets Guardian alert you in the background.",
    microphone: "Microphone/audio: lets Guardian hear and speak confirmations.",
  };
  return labels[key];
}

function labelEscort(state?: string) {
  const labels: Record<string, string> = {
    on_track: "On track",
    tier1_redirect: "Tier 1 redirect",
    tier2_checkin: "Tier 2 check-in",
    tier3_dispatch: "Tier 3 dispatch",
  };
  return state ? labels[state] ?? state : "";
}

function speechLang(code?: string) {
  return code?.toLowerCase().startsWith("vi") ? "vi-VN" : "en-US";
}
