export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

export type Severity = "green" | "yellow" | "red";

export interface Rider {
  id: string;
  name: string;
  preferred_language: string;
  phone: string;
  permissions: Record<string, boolean>;
}

export interface Dispatcher {
  id: string;
  name: string;
  languages: string;
  phone: string;
  on_duty: boolean;
}

export interface Trip {
  id: string;
  rider_id: string;
  destination_name: string;
  route_name: string;
  status: string;
  severity: Severity;
  route_shape: [number, number][];
  milestones: { label: string; complete: boolean }[];
  locations?: { lat: number; lon: number; source: string; recorded_at: string }[];
  rider?: { name: string; preferred_language: string; phone: string };
  alerts?: Alert[];
  resolution?: { spoken_confirmation: string };
}

export interface Alert {
  id: string;
  trip_id: string;
  deviation_type: string;
  tier: number;
  severity: Severity;
  status: string;
  assigned_dispatcher_id?: string;
  triage: {
    severity: string;
    summary: string;
    recommended_action: string;
    rider_phrase: string;
  };
  rider?: { name: string; phone: string };
  trip?: { destination_name: string; route_name: string };
}

export interface Snapshot {
  riders: Rider[];
  dispatchers: Dispatcher[];
  trips: Trip[];
  alerts: Alert[];
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

export const api = {
  snapshot: () => request<Snapshot>("/snapshot"),
  createTrip: (destination: string) =>
    request<Trip>("/trips", { method: "POST", body: JSON.stringify({ rider_id: "rider_nguyen", destination, mode: "voice" }) }),
  updatePermissions: (permissions: Record<string, boolean>) =>
    request("/riders/rider_nguyen/permissions", { method: "PATCH", body: JSON.stringify(permissions) }),
  setDuty: (dispatcherId: string, onDuty: boolean) =>
    request(`/dispatchers/${dispatcherId}/duty`, { method: "POST", body: JSON.stringify({ on_duty: onDuty }) }),
  claimAlert: (alertId: string) => request<Alert>(`/alerts/${alertId}/claim`, { method: "POST" }),
  escalateAlert: (alertId: string) => request<Alert>(`/alerts/${alertId}/escalate`, { method: "POST" }),
  runDemo: (scenario: string) => request<Trip>(`/demo/run/${scenario}`, { method: "POST" }),
  resetDemo: () => request("/demo/reset", { method: "POST" }),
};
