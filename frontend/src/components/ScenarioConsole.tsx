import { useState } from "react";
import { FlaskConical, ArrowRight, AlertTriangle } from "lucide-react";
import { apiFetch } from "../lib/apiClient";

/**
 * Scenario console — the demand side of the blocking loop.
 *
 * The blocking plan answers "what does today's timetable need?". This answers
 * "what would a different one need?" — extra buses, from which depot, at what
 * dead-km and crew consequence. It is the screen to hand to the person you are
 * presenting to: they type the change they have been arguing about internally,
 * and the cost appears.
 */

type Metrics = {
  trips: number;
  buses: number;
  buses_floor: number;
  revenue_km: number;
  dead_km: number | null;
  idle_bus_hours: number;
  trips_per_bus: number;
  over_duty_blocks: number;
  total_blocks: number;
  median_block_span_hours: number;
};

const num = (v: number) => (v ?? 0).toLocaleString("en-IN");
const signed = (v: number) => (v > 0 ? `+${num(v)}` : num(v));

export default function ScenarioConsole({ token }: { token: string | null }) {
  const [route, setRoute] = useState("375-D");
  const [action, setAction] = useState("set_headway");
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("10:00");
  const [headway, setHeadway] = useState(5);
  const [trips, setTrips] = useState(10);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string>("");
  const [hints, setHints] = useState<string[]>([]);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    setError("");
    setHints([]);
    try {
      const body: any = {
        route_number: route.trim(),
        action,
        start_time: start,
        end_time: end,
      };
      if (action === "set_headway") body.headway_minutes = Number(headway);
      if (action === "add_trips") body.trips = Number(trips);

      const res = await apiFetch(`/depot/blocking-scenario`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        const detail = data?.detail;
        setError(typeof detail === "string" ? detail : detail?.message || "Scenario failed.");
        if (detail?.did_you_mean) setHints(detail.did_you_mean);
        setResult(null);
      } else {
        setResult(data);
      }
    } catch (e: any) {
      setError(e?.message || "Scenario failed.");
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  const before: Metrics | null = result?.before ?? null;
  const after: Metrics | null = result?.after ?? null;
  const delta = result?.delta ?? null;

  const field = {
    padding: "8px 10px",
    borderRadius: 8,
    background: "var(--surface-strong)",
    color: "var(--text)",
    border: "1px solid var(--line-strong)",
    fontSize: "0.88rem",
  } as const;

  return (
    <div
      className="bento-card"
      style={{
        padding: "1.75rem",
        marginBottom: "2rem",
        background: "var(--surface-glass)",
        backdropFilter: "blur(16px)",
        border: "1px solid var(--line-strong)",
      }}
    >
      <div style={{ marginBottom: "1.25rem" }}>
        <h3 className="bento-title" style={{ fontSize: "1.25rem", margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
          <FlaskConical size={20} className="text-accent" /> Scenario Console
        </h3>
        <p className="text-muted" style={{ fontSize: "0.85rem", margin: "4px 0 0 0", maxWidth: 660, lineHeight: 1.45 }}>
          Change the timetable and see what it costs before committing to it — extra buses,
          which depot they come from, and whether the result is still crew-feasible.
        </p>
      </div>

      {/* ── Controls ─────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap", alignItems: "flex-end", marginBottom: "1.25rem" }}>
        <Labelled label="Route">
          <input value={route} onChange={(e) => setRoute(e.target.value)} style={{ ...field, width: 130 }} placeholder="375-D" />
        </Labelled>
        <Labelled label="Change">
          <select value={action} onChange={(e) => setAction(e.target.value)} style={{ ...field, width: 165 }}>
            <option value="set_headway">Set headway</option>
            <option value="add_trips">Add trips</option>
            <option value="remove_trips">Remove trips</option>
          </select>
        </Labelled>
        <Labelled label="From">
          <input value={start} onChange={(e) => setStart(e.target.value)} style={{ ...field, width: 85 }} placeholder="08:00" />
        </Labelled>
        <Labelled label="To">
          <input value={end} onChange={(e) => setEnd(e.target.value)} style={{ ...field, width: 85 }} placeholder="10:00" />
        </Labelled>
        {action === "set_headway" && (
          <Labelled label="Every (min)">
            <input type="number" min={1} max={240} value={headway} onChange={(e) => setHeadway(+e.target.value)} style={{ ...field, width: 95 }} />
          </Labelled>
        )}
        {action === "add_trips" && (
          <Labelled label="Trips">
            <input type="number" min={1} max={500} value={trips} onChange={(e) => setTrips(+e.target.value)} style={{ ...field, width: 95 }} />
          </Labelled>
        )}
        <button
          className="bento-btn"
          onClick={run}
          disabled={running}
          style={{ padding: "9px 18px", borderRadius: 9, background: "var(--gradient-brand)", color: "#fff", border: "none", fontWeight: 700, fontSize: "0.88rem" }}
        >
          {running ? "Running…" : "Run scenario"}
        </button>
      </div>

      {error && (
        <div style={{ padding: "0.85rem 1rem", borderRadius: 10, background: "#f43f5e15", border: "1px solid #f43f5e55", marginBottom: "1rem" }}>
          <p style={{ margin: 0, fontSize: "0.85rem", color: "#f43f5e" }}>{error}</p>
          {hints.length > 0 && (
            <p style={{ margin: "6px 0 0 0", fontSize: "0.8rem", color: "var(--text-2)" }}>
              Try:{" "}
              {hints.map((h) => (
                <button
                  key={h}
                  onClick={() => { setRoute(h); setError(""); setHints([]); }}
                  style={{ background: "none", border: "none", color: "var(--accent, #00e5c8)", cursor: "pointer", padding: "0 6px 0 0", fontSize: "0.8rem" }}
                >
                  {h}
                </button>
              ))}
            </p>
          )}
        </div>
      )}

      {/* ── Result ───────────────────────────────────────────────────────── */}
      {result && before && after && delta && (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: "1rem" }}>
            <span style={{ fontSize: "0.9rem", fontWeight: 700 }}>{result.scenario.description}</span>
            <span className="text-muted" style={{ fontSize: "0.82rem" }}>
              at {result.depot.label} · timetable {num(result.timetable.trips_before)} →{" "}
              {num(result.timetable.trips_after)} trips ({signed(result.timetable.trips_delta)})
            </span>
          </div>

          <div className="admin-table-container">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Depot metric</th>
                  <th style={{ textAlign: "right" }}>Now</th>
                  <th style={{ textAlign: "right" }}>Scenario</th>
                  <th style={{ textAlign: "right" }}>Change</th>
                </tr>
              </thead>
              <tbody>
                {/* Colour judges COST, not direction. More trips is the change
                    being asked for, not a regression, so service rows stay
                    neutral; only the rows that represent a price are red. */}
                <Row label="Buses required" a={before.buses} b={after.buses} d={delta.buses} highlight />
                <Row label="Trips operated" a={before.trips} b={after.trips} d={delta.trips} neutral />
                <Row label="Revenue km / day" a={before.revenue_km} b={after.revenue_km} d={delta.revenue_km} neutral />
                <Row label="Dead km / day" a={before.dead_km} b={after.dead_km} d={delta.dead_km} />
                <Row label="Idle bus-hours" a={before.idle_bus_hours} b={after.idle_bus_hours} d={delta.idle_bus_hours} />
                <Row label="Trips per bus" a={before.trips_per_bus} b={after.trips_per_bus} d={after.trips_per_bus - before.trips_per_bus} invert />
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: "1rem", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {(result.notes || []).map((n: string, i: number) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "0.7rem 0.9rem", borderRadius: 9, background: "var(--surface-sunken)", border: "1px solid var(--line-strong)" }}>
                <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: 2 }} className="text-accent" />
                <span style={{ fontSize: "0.83rem", lineHeight: 1.5, color: "var(--text-2)" }}>{n}</span>
              </div>
            ))}
          </div>

          <p className="text-muted" style={{ fontSize: "0.76rem", margin: "1rem 0 0 0", lineHeight: 1.5 }}>
            Assumes {result.assumptions.average_speed_kmph} km/h running speed,{" "}
            {result.assumptions.layover_minutes} min layover, ≤{result.assumptions.max_deadhead_km} km empty
            repositioning. The bus counts are only as good as those figures — replace them with BMTC's
            scheduled running times before treating any of this as a cost estimate.
          </p>
        </>
      )}
    </div>
  );
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontSize: "0.74rem", fontWeight: 700, color: "var(--text-2)" }}>{label}</label>
      {children}
    </div>
  );
}

function Row({
  label, a, b, d, highlight, neutral, invert,
}: {
  label: string; a: number | null; b: number | null; d: number | null;
  highlight?: boolean; neutral?: boolean; invert?: boolean;
}) {
  // null means "we will not quote this" — an inferred depot assignment cannot
  // support a dead-km figure. Blank, never zero: a zero would read as a fact.
  if (a === null || b === null || d === null) {
    return (
      <tr>
        <td>{label}</td>
        <td style={{ textAlign: "right" }} className="text-muted">—</td>
        <td style={{ textAlign: "right" }} className="text-muted">—</td>
        <td style={{ textAlign: "right" }} className="text-muted">—</td>
      </tr>
    );
  }
  // "More buses" is a cost; "more trips per bus" is a gain; "more trips
  // operated" is simply the change that was requested. Colour by meaning, not
  // by sign, or the table reads backwards on half its rows.
  const good = neutral || d === 0 ? null : invert ? d > 0 : d < 0;
  const colour = good === null ? "var(--text-3)" : good ? "#10b981" : "#f43f5e";
  return (
    <tr>
      <td style={highlight ? { fontWeight: 700 } : undefined}>{label}</td>
      <td style={{ textAlign: "right" }}>{num(a)}</td>
      <td style={{ textAlign: "right", fontWeight: highlight ? 700 : 400 }}>{num(b)}</td>
      <td style={{ textAlign: "right", color: colour, fontWeight: 700 }}>
        {d === 0 ? "—" : signed(Math.round(d * 10) / 10)}
      </td>
    </tr>
  );
}
