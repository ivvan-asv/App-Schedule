"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  CalendarEvent,
  ParsedEvent,
  createEvent,
  createNegotiation,
  listEvents,
  parseIntent,
} from "../lib/api";

export default function HomePage() {
  const [text, setText] = useState("Agendá mañana a las 15 una reunión con Ana en Palermo");
  const [recipient, setRecipient] = useState("");
  const [parsed, setParsed] = useState<ParsedEvent | null>(null);
  const [source, setSource] = useState("");
  const [travel, setTravel] = useState(0);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [message, setMessage] = useState("");
  const [confirmUrl, setConfirmUrl] = useState("");
  const [loading, setLoading] = useState(false);

  async function refreshEvents() {
    try {
      setEvents(await listEvents());
    } catch {
      setEvents([]);
    }
  }

  useEffect(() => {
    refreshEvents();
  }, []);

  async function onParse(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      const result = await parseIntent(text);
      setParsed(result.parsed);
      setSource(result.source);
      setTravel(result.travel_before_minutes);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo interpretar la intención");
    } finally {
      setLoading(false);
    }
  }

  async function onSave() {
    if (!parsed) return;
    setLoading(true);
    try {
      await createEvent({ ...parsed, source_text: text, travel_before_minutes: travel });
      setMessage("Evento confirmado en el calendario local.");
      await refreshEvents();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo guardar");
    } finally {
      setLoading(false);
    }
  }

  async function onInvite() {
    if (!parsed || !recipient) return;
    setLoading(true);
    try {
      const negotiation = await createNegotiation({
        title: parsed.title,
        duration_minutes: parsed.duration_minutes,
        recipient,
        channel: "email",
        proposed_starts: [parsed.start_time],
      });
      setConfirmUrl(negotiation.confirm_url);
      setMessage(`Invitación lista para ${recipient}. WhatsApp/SMS se conectan en Fase 3.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo crear la invitación");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-12">
      <header>
        <p className="text-sm uppercase tracking-[0.2em] text-emerald-400">Smart Scheduler AI</p>
        <h1 className="mt-2 text-4xl font-semibold">De la intención al bloque de tiempo</h1>
        <p className="mt-3 max-w-2xl text-slate-400">
          Captura en lenguaje natural, extracción estructurada, buffer de traslado y confirmación.
          El mismo contrato lo van a usar Expo, App Intents y el portal de terceros.
        </p>
      </header>

      <form onSubmit={onParse} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
        <label className="text-sm text-slate-400">Qué querés agendar</label>
        <textarea
          className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 p-4 outline-none focus:border-emerald-400"
          rows={3}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <button
          className="mt-4 rounded-full bg-emerald-400 px-5 py-2 font-medium text-slate-950 disabled:opacity-50"
          disabled={loading}
        >
          Interpretar
        </button>
      </form>

      {parsed && (
        <section className="grid gap-6 rounded-2xl border border-slate-800 bg-slate-900/60 p-6 md:grid-cols-2">
          <div>
            <p className="text-sm text-emerald-400">Fuente: {source}</p>
            <h2 className="text-2xl font-medium">{parsed.title}</h2>
            <p className="mt-2 text-slate-300">{new Date(parsed.start_time).toLocaleString()}</p>
            <p className="text-slate-400">{parsed.duration_minutes} min · {parsed.location || "Sin lugar"}</p>
            <p className="text-slate-400">Traslado estimado: {travel} min</p>
            {parsed.attendees.length > 0 && <p>Con {parsed.attendees.join(", ")}</p>}
          </div>
          <div className="flex flex-col gap-3">
            <button onClick={onSave} className="rounded-full bg-white px-5 py-2 text-slate-950" disabled={loading}>
              Confirmar en calendario
            </button>
            <input
              className="rounded-xl border border-slate-700 bg-slate-950 p-3"
              placeholder="Email, teléfono o WhatsApp del invitado"
              value={recipient}
              onChange={(event) => setRecipient(event.target.value)}
            />
            <button onClick={onInvite} className="rounded-full border border-emerald-400 px-5 py-2 text-emerald-300" disabled={loading}>
              Generar link de confirmación
            </button>
            {confirmUrl && (
              <a className="break-all text-sm text-emerald-400 underline" href={confirmUrl}>
                {confirmUrl}
              </a>
            )}
          </div>
        </section>
      )}

      {message && <p className="text-amber-300">{message}</p>}

      <section>
        <h2 className="mb-4 text-xl font-medium">Agenda</h2>
        <div className="grid gap-3">
          {events.map((item) => (
            <article key={item.id} className="rounded-xl border border-slate-800 p-4">
              <h3 className="font-medium">{item.title}</h3>
              <p className="text-sm text-slate-400">
                {new Date(item.start_time).toLocaleString()} → {new Date(item.end_time).toLocaleString()}
              </p>
            </article>
          ))}
          {events.length === 0 && <p className="text-slate-500">Todavía no hay eventos.</p>}
        </div>
      </section>
    </main>
  );
}
