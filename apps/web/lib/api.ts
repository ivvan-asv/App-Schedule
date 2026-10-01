const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export type ParsedEvent = {
  title: string;
  start_time: string;
  duration_minutes: number;
  location: string | null;
  priority: string;
  notes: string | null;
  attendees: string[];
  needs_travel: boolean;
  origin_location: string | null;
};

export type CalendarEvent = {
  id: string;
  title: string;
  start_time: string;
  end_time: string;
  location: string | null;
  status: string;
  attendees: string[];
  travel_before_minutes: number;
};

export type Negotiation = {
  id: string;
  public_token: string;
  title: string;
  recipient: string;
  channel: string;
  proposed_starts: string[];
  status: string;
  confirm_url: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export function parseIntent(text: string) {
  return request<{ parsed: ParsedEvent; source: string; travel_before_minutes: number }>(
    "/intents/parse",
    { method: "POST", body: JSON.stringify({ text, timezone: "America/Argentina/Buenos_Aires" }) },
  );
}

export function createEvent(payload: ParsedEvent & { source_text?: string; travel_before_minutes?: number }) {
  return request<CalendarEvent>("/events", {
    method: "POST",
    body: JSON.stringify({
      title: payload.title,
      start_time: payload.start_time,
      duration_minutes: payload.duration_minutes,
      location: payload.location,
      priority: payload.priority,
      notes: payload.notes,
      attendees: payload.attendees,
      source_text: payload.source_text,
      travel_before_minutes: payload.travel_before_minutes || 0,
      commit_to_calendar: true,
    }),
  });
}

export function listEvents() {
  return request<CalendarEvent[]>("/events");
}

export function getNegotiation(token: string) {
  return request<Negotiation>(`/negotiations/${token}`);
}

export function confirmNegotiation(token: string, selected_start: string) {
  return request<CalendarEvent>("/negotiations/confirm", {
    method: "POST",
    body: JSON.stringify({ token, selected_start }),
  });
}

export function createNegotiation(body: {
  title: string;
  duration_minutes: number;
  recipient: string;
  channel: string;
  proposed_starts: string[];
}) {
  return request<Negotiation>("/negotiations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
