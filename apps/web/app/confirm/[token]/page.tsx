"use client";

import { useEffect, useState } from "react";
import { CalendarEvent, Negotiation, confirmNegotiation, getNegotiation } from "../../../lib/api";

export default function ConfirmPage({ params }: { params: { token: string } }) {
  const [negotiation, setNegotiation] = useState<Negotiation | null>(null);
  const [event, setEvent] = useState<CalendarEvent | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getNegotiation(params.token).then(setNegotiation).catch((err: Error) => setError(err.message));
  }, [params.token]);

  async function choose(start: string) {
    try {
      const created = await confirmNegotiation(params.token, start);
      setEvent(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo confirmar");
    }
  }

  if (error) {
    return <main className="mx-auto max-w-xl px-6 py-16 text-amber-300">{error}</main>;
  }

  if (!negotiation) {
    return <main className="mx-auto max-w-xl px-6 py-16 text-slate-400">Cargando invitación…</main>;
  }

  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <p className="text-sm uppercase tracking-[0.2em] text-emerald-400">Confirmación rápida</p>
      <h1 className="mt-3 text-3xl font-semibold">{negotiation.title}</h1>
      <p className="mt-2 text-slate-400">Elegí un horario. No hace falta crear cuenta.</p>
      {event ? (
        <p className="mt-8 rounded-2xl border border-emerald-400/40 p-6">
          Confirmado para {new Date(event.start_time).toLocaleString()}
        </p>
      ) : (
        <div className="mt-8 grid gap-3">
          {negotiation.proposed_starts.map((start) => (
            <button
              key={start}
              onClick={() => choose(start)}
              className="rounded-2xl border border-slate-700 bg-slate-900 p-4 text-left hover:border-emerald-400"
            >
              {new Date(start).toLocaleString()}
            </button>
          ))}
        </div>
      )}
    </main>
  );
}
