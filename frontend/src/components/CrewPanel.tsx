import { useEffect, useMemo, useState } from "react";
import { Users, AlertTriangle, RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/apiClient";

/**
 * Crew duty plan — the companion to BlockingPanel.
 *
 * BlockingPanel answers "how few buses can hold this timetable". This answers
 * the objection that question invites: a plan that saves buses by chaining one
 * across fourteen hours has saved nothing unless a roster can staff it.
 *
 * The rule console at the bottom is the point of the panel rather than a
 * decoration. A crew agreement is negotiated one clause at a time, and the
 * only useful thing software can say about a proposed clause is what it costs
 * in duties — which is what POST /depot/crew-scenario returns.
 */

type DepotCrew = {
  key: string;
  label: string;
  zone: string;
  routes: number;
  blocks: number;
  pieces: number;
  duties: number;
  duties_floor: number;
  provably_minimal: boolean;
  crew_to_bus_ratio: number;
  split_duties: number;
  split_duty_pct: number;
  paid_hours: number;
  median_working_hours: number;
  median_spreadover_hours: number;
  max_spreadover_hours: number;
  unstaffable_blocks: number;
  unstaffable_examples: string[];
};

type Scenario = {
  before: DepotCrew;
  after: DepotCrew;
  delta: Record<string, number>;
  notes: string[];
};

const num = (value: number) => value.toLocaleString("en-IN");

export default function CrewPanel({ token }: { token: string | null }) {
  const [plan, setPlan] = useState<any>(null);
  const [depotKey, setDepotKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [maxWorking, setMaxWorking] = useState(480);
  const [maxSpreadover, setMaxSpreadover] = useState(720);
  const [allowSplits, setAllowSplits] = useState(true);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [running, setRunning] = useState(false);
  const [scenarioError, setScenarioError] = useState("");

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    apiFetch(`/depot/crew-plan`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => {
        setPlan(data);
        if (data?.depots?.length) setDepotKey(data.depots[0].key);
      })
      .catch(() => setError("Could not load the crew plan."))
      .finally(() => setLoading(false));
  }, [token]);

  const depot: DepotCrew | null = useMemo(
    () => plan?.depots?.find((d: DepotCrew) => d.key === depotKey) ?? null,
    [plan, depotKey],
  );

  const runScenario = async () => {
    if (!depotKey) return;
    setRunning(true);
    setScenarioError("");
    setScenario(null);
    try {
      const response = await apiFetch(`/depot/crew-scenario`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          depot: depotKey,
          max_working_minutes: maxWorking,
          max_spreadover_minutes: maxSpreadover,
          allow_split_duties: allowSplits,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        // The 422 from the endpoint carries a real explanation (paid time is
        // part of the spreadover, not additional to it) — show it rather than
        // a generic failure.
        setScenarioError(typeof data.detail === "string" ? data.detail : "Could not run that scenario.");
        return;
      }
      setScenario(data);
    } catch {
      setScenarioError("Could not run that scenario.");
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="bento-card" style={{ padding: "1.75rem", marginTop: "2rem" }}>
        <p className="text-muted" style={{ margin: 0 }}>Scheduling crew duties…</p>
      </div>
    );
  }
  if (error || !plan?.network) {
    return (
      <div className="bento-card" style={{ padding: "1.75rem", marginTop: "2rem" }}>
        <p className="text-muted" style={{ margin: 0 }}>{error || "No crew plan available."}</p>
      </div>
    );
  }

  const net = plan.network;

  return (
    <div className="bento-card" style={{ padding: "1.75rem", marginTop: "2rem" }}>
      <div style={{ marginBottom: "1.25rem" }}>
        <h3 className="bento-title" style={{ fontSize: "1.2rem", margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
          <Users size={20} className="text-accent" /> Crew Duties
        </h3>
        <p className="text-muted" style={{ fontSize: "0.85rem", margin: "4px 0 0 0" }}>
          A block is a bus's day; a duty is a person's. {num(net.blocks)} blocks cut into{" "}
          {num(net.pieces)} pieces of work, combined into {num(net.duties)} daily duties.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "0.85rem", marginBottom: "1.25rem" }}>
        <Cell label="Daily duties" value={num(net.duties)} sub="citywide" accent />
        <Cell label="Crew per bus" value={String(net.crew_to_bus_ratio)} sub="real ≈ 2.0–2.5" />
        <Cell label="Hard floor" value={num(net.duties_floor)} sub="unbeatable" />
        <Cell label="Split duties" value={`${net.split_duty_pct}%`} sub={`${num(net.split_duties)} of ${num(net.duties)}`} />
        <Cell label="Median day" value={`${net.median_working_hours}h`} sub={`spread ${net.median_spreadover_hours}h`} />
      </div>

      {net.unstaffable_blocks > 0 && (
        <div style={{ display: "flex", gap: 10, padding: "0.85rem 1rem", borderRadius: 12, background: "var(--surface-strong)", border: "1px solid #f59e0b55", marginBottom: "1.25rem" }}>
          <AlertTriangle size={18} style={{ color: "#f59e0b", flexShrink: 0, marginTop: 2 }} />
          <div style={{ fontSize: "0.8rem", lineHeight: 1.5 }}>
            <strong>{num(net.unstaffable_blocks)} blocks cannot be staffed</strong> under these rules —
            they offer no legal relief opportunity long enough to hand the bus over. These need a
            timetable change, not a rostering change.
            {net.unstaffable_examples?.length > 0 && (
              <div className="text-muted" style={{ marginTop: 4 }}>
                e.g. {net.unstaffable_examples.slice(0, 4).join(", ")}
              </div>
            )}
          </div>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: "0.85rem", flexWrap: "wrap" }}>
        <label className="text-muted" style={{ fontSize: "0.8rem" }}>Depot</label>
        <select
          className="input"
          value={depotKey}
          onChange={(event) => { setDepotKey(event.target.value); setScenario(null); }}
          style={{ maxWidth: 320 }}
        >
          {(plan.depots || []).map((d: DepotCrew) => (
            <option key={d.key} value={d.key}>{d.label} — {num(d.duties)} duties</option>
          ))}
        </select>
      </div>

      {depot && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "0.85rem", marginBottom: "1.5rem" }}>
          <Cell label="Buses" value={num(depot.blocks)} sub={`${num(depot.routes)} routes`} />
          <Cell label="Duties" value={num(depot.duties)} sub={depot.provably_minimal ? "provably minimal" : `floor ${num(depot.duties_floor)}`} accent />
          <Cell label="Crew per bus" value={String(depot.crew_to_bus_ratio)} />
          <Cell label="Split duties" value={`${depot.split_duty_pct}%`} />
          <Cell label="Longest spread" value={`${depot.max_spreadover_hours}h`} />
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--line-strong)", paddingTop: "1.25rem" }}>
        <h4 style={{ margin: "0 0 0.25rem 0", fontSize: "0.95rem", fontWeight: 700 }}>
          What would a rule change cost?
        </h4>
        <p className="text-muted" style={{ fontSize: "0.78rem", margin: "0 0 1rem 0" }}>
          Every crew rule below is an assumption, not a BMTC figure. Change one and see the
          staffing consequence at this depot before agreeing to it.
        </p>

        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "flex-end" }}>
          <Field label="Max working day (min)">
            <input className="input" type="number" min={120} max={720} step={15}
              value={maxWorking} onChange={(e) => setMaxWorking(Number(e.target.value))} style={{ width: 120 }} />
          </Field>
          <Field label="Max spreadover (min)">
            <input className="input" type="number" min={120} max={1080} step={30}
              value={maxSpreadover} onChange={(e) => setMaxSpreadover(Number(e.target.value))} style={{ width: 120 }} />
          </Field>
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.85rem", paddingBottom: 8 }}>
            <input type="checkbox" checked={allowSplits} onChange={(e) => setAllowSplits(e.target.checked)} />
            Allow split duties
          </label>
          <button className="btn btn-primary" onClick={runScenario} disabled={running || !depotKey} style={{ marginBottom: 4 }}>
            {running ? <RefreshCw size={15} className="spin" /> : null} Run scenario
          </button>
        </div>

        {scenarioError && (
          <p style={{ color: "#f87171", fontSize: "0.82rem", marginTop: "0.85rem" }}>{scenarioError}</p>
        )}

        {scenario && (
          <div style={{ marginTop: "1.25rem" }}>
            <div className="admin-table-container">
              <table className="admin-table">
                <thead>
                  <tr><th>Measure</th><th>Now</th><th>Proposed</th><th>Change</th></tr>
                </thead>
                <tbody>
                  <Row label="Daily duties" before={scenario.before.duties} after={scenario.after.duties} invert />
                  <Row label="Split duties" before={scenario.before.split_duties} after={scenario.after.split_duties} invert />
                  <Row label="Paid hours" before={scenario.before.paid_hours} after={scenario.after.paid_hours} invert />
                  <Row label="Unstaffable blocks" before={scenario.before.unstaffable_blocks} after={scenario.after.unstaffable_blocks} invert />
                </tbody>
              </table>
            </div>
            <ul style={{ margin: "0.85rem 0 0 0", paddingLeft: "1.1rem", fontSize: "0.82rem", lineHeight: 1.6 }}>
              {scenario.notes.map((note, index) => <li key={index}>{note}</li>)}
            </ul>
          </div>
        )}
      </div>

      <p className="text-muted" style={{ fontSize: "0.76rem", margin: "1.25rem 0 0 0", lineHeight: 1.5 }}>
        {plan.caveats?.[0]}{" "}
        {plan.caveats?.[2]}
      </p>
    </div>
  );
}

function Row({ label, before, after, invert }: { label: string; before: number; after: number; invert?: boolean }) {
  const delta = Math.round((after - before) * 100) / 100;
  // More duties is worse, so the "good" colour is the negative direction here.
  const good = invert ? delta < 0 : delta > 0;
  const colour = delta === 0 ? "var(--text-3)" : good ? "#10b981" : "#f87171";
  return (
    <tr>
      <td><strong>{label}</strong></td>
      <td>{before.toLocaleString("en-IN")}</td>
      <td>{after.toLocaleString("en-IN")}</td>
      <td style={{ color: colour, fontWeight: 700 }}>
        {delta > 0 ? "+" : ""}{delta.toLocaleString("en-IN")}
      </td>
    </tr>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label className="text-muted" style={{ fontSize: "0.76rem" }}>{label}</label>
      {children}
    </div>
  );
}

function Cell({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div style={{ padding: "0.9rem 1rem", borderRadius: 12, background: "var(--surface-strong)", border: "1px solid var(--line-strong)" }}>
      <div style={{ fontSize: "1.4rem", fontWeight: 800, lineHeight: 1.1, color: accent ? "var(--accent, #00e5c8)" : "var(--text)" }}>{value}</div>
      <div style={{ fontSize: "0.76rem", fontWeight: 600, marginTop: 4 }}>{label}</div>
      {sub && <div style={{ fontSize: "0.7rem", color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
