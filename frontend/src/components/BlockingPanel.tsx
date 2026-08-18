import { useEffect, useMemo, useState } from "react";
import { Layers, Check, X, Info, RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/apiClient";

/**
 * Vehicle blocking plan — the operator-facing panel.
 *
 * Shows the same timetable scheduled two ways: each route name holding its own
 * dedicated buses, versus buses chained across route names. Trips, headways and
 * passengers served are identical between the two columns; only the assignment
 * of buses to trips differs, and the difference is the fleet released.
 *
 * Deliberately advisory. Each proposal is approved or rejected by a named
 * person and nothing dispatches — see POST /depot/blocking-decision.
 */

type Proposal = {
  route: string;
  trips: number;
  buses_scheduled: number;
  buses_floor: number;
  buses_released: number;
  revenue_km: number;
  dead_km: number | null;
  depot_source: string;
  provably_minimal: boolean;
};

type DepotPlan = {
  key: string;
  label: string;
  zone: string;
  routes: number;
  trips: number;
  revenue_km: number;
  buses_scheduled: number;
  buses_interlined: number;
  buses_released: number;
  buses_floor: number;
  dead_km_stated: number;
  routes_depot_stated: number;
  routes_depot_inferred: number;
  proposals: Proposal[];
};

const num = (value: number) => value.toLocaleString("en-IN");

export default function BlockingPanel({ token }: { token: string | null }) {
  const [plan, setPlan] = useState<any>(null);
  const [depotKey, setDepotKey] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const [decisions, setDecisions] = useState<Record<string, "approve" | "reject">>({});
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    apiFetch(`/depot/blocking-plan`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => {
        setPlan(data);
        if (data?.depots?.length) setDepotKey(data.depots[0].key);
      })
      .catch(() => setError("Could not load the blocking plan."))
      .finally(() => setLoading(false));
  }, [token]);

  const depot: DepotPlan | null = useMemo(
    () => plan?.depots?.find((d: DepotPlan) => d.key === depotKey) ?? null,
    [plan, depotKey],
  );

  const decide = async (proposal: Proposal, decision: "approve" | "reject") => {
    if (!depot) return;
    const key = `${depot.key}:${proposal.route}`;
    setSaving(key);
    try {
      await apiFetch(`/depot/blocking-decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          depot: depot.key,
          route_number: proposal.route,
          decision,
          buses_released: proposal.buses_released,
        }),
      });
      setDecisions((prev) => ({ ...prev, [key]: decision }));
    } catch {
      /* leave the row undecided so it can be retried */
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return (
      <div className="bento-card" style={{ padding: "1.75rem", marginBottom: "2rem" }}>
        <p className="text-muted" style={{ margin: 0 }}>
          Computing the blocking plan from the published timetable…
        </p>
      </div>
    );
  }

  if (error || !plan?.network) {
    return (
      <div className="bento-card" style={{ padding: "1.75rem", marginBottom: "2rem" }}>
        <p className="text-muted" style={{ margin: 0 }}>{error || "No blocking plan available."}</p>
      </div>
    );
  }

  const net = plan.network;
  const approvedBuses = depot
    ? depot.proposals
        .filter((p) => decisions[`${depot.key}:${p.route}`] === "approve")
        .reduce((sum, p) => sum + p.buses_released, 0)
    : 0;

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
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem", marginBottom: "1.5rem" }}>
        <div>
          <h3 className="bento-title" style={{ fontSize: "1.25rem", margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
            <Layers size={20} className="text-accent" /> Fleet Blocking Plan
          </h3>
          <p className="text-muted" style={{ fontSize: "0.85rem", margin: "4px 0 0 0", maxWidth: 640, lineHeight: 1.45 }}>
            Computed from BMTC's own published timetable — {num(net.trips)} scheduled trips
            across {num(net.passenger_routes)} passenger routes. No ridership data, no
            surveys, no sensors.
          </p>
        </div>
        <span style={{ fontSize: "0.72rem", color: "var(--text-3)", whiteSpace: "nowrap" }}>
          {plan.generated_at}
        </span>
      </div>

      {/* ── Network before/after ─────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.85rem", marginBottom: "1.5rem" }}>
        <Stat label="Buses, as scheduled" value={num(net.buses_scheduled)} hint="each route name separate" />
        <Stat label="Buses, interlined" value={num(net.buses_interlined)} hint="chained across route names" accent />
        <Stat label="Buses released" value={num(net.buses_released)} hint={`${((net.buses_released / net.buses_scheduled) * 100).toFixed(0)}% of the baseline`} good />
        <Stat label="Theoretical floor" value={num(net.buses_floor)} hint="no schedule can beat this" />
        <Stat label="Km per bus / day" value={num(net.km_per_bus)} hint="real BMTC ≈ 180–200" />
      </div>

      <div style={{ padding: "0.85rem 1rem", borderRadius: 10, background: "var(--surface-sunken)", border: "1px solid var(--line-strong)", marginBottom: "1.5rem", display: "flex", gap: 10, alignItems: "flex-start" }}>
        <Info size={16} style={{ flexShrink: 0, marginTop: 2 }} className="text-accent" />
        <p style={{ margin: 0, fontSize: "0.83rem", lineHeight: 1.5, color: "var(--text-2)" }}>
          <strong>Same trips, same headways, same passengers served.</strong> The only thing
          that changes is which bus runs which trip. At {num(net.km_per_bus)} km and{" "}
          {net.trips_per_bus} trips per bus per day against a real 180–200 km and 8–12 trips,
          this figure is conservative — it understates what is achievable.
        </p>
      </div>

      {/* ── Depot picker ─────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        <label style={{ fontSize: "0.85rem", fontWeight: 600 }}>Depot</label>
        <select
          value={depotKey}
          onChange={(e) => setDepotKey(e.target.value)}
          style={{ padding: "8px 12px", borderRadius: 8, background: "var(--surface-strong)", color: "var(--text)", border: "1px solid var(--line-strong)", minWidth: 280, fontSize: "0.88rem" }}
        >
          {plan.depots.map((d: DepotPlan) => (
            <option key={d.key} value={d.key}>
              {d.label} — {num(d.buses_released)} buses released
            </option>
          ))}
        </select>
        {depot && (
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>
            {num(depot.routes)} routes · {num(depot.trips)} trips/day
            {depot.zone ? ` · ${depot.zone} zone` : ""}
          </span>
        )}
      </div>

      {depot && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.85rem", marginBottom: "1.25rem" }}>
            <Stat label="Depot buses, scheduled" value={num(depot.buses_scheduled)} />
            <Stat label="Depot buses, interlined" value={num(depot.buses_interlined)} accent />
            <Stat label="Released at this depot" value={num(depot.buses_released)} good />
            <Stat
              label="Dead km / day"
              value={depot.routes_depot_stated ? num(Math.round(depot.dead_km_stated)) : "—"}
              hint={
                depot.routes_depot_stated
                  ? `${depot.routes_depot_stated} routes with depot stated`
                  : "needs BMTC route→depot mapping"
              }
            />
            {approvedBuses > 0 && <Stat label="Approved so far" value={num(approvedBuses)} hint="buses released" good />}
          </div>

          <h4 style={{ fontSize: "0.95rem", margin: "0 0 0.5rem 0" }}>
            Proposed re-blocks <span className="text-muted" style={{ fontWeight: 400 }}>— approve or reject each</span>
          </h4>

          {depot.proposals.length === 0 ? (
            <p className="text-muted" style={{ fontSize: "0.86rem", margin: 0 }}>
              Every route at this depot is already running at its theoretical minimum. No
              change proposed.
            </p>
          ) : (
            <div className="admin-table-container">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Route</th>
                    <th>Trips</th>
                    <th>Buses now</th>
                    <th>Floor</th>
                    <th>Release</th>
                    <th>Dead km</th>
                    <th style={{ textAlign: "right" }}>Decision</th>
                  </tr>
                </thead>
                <tbody>
                  {depot.proposals.map((p) => {
                    const key = `${depot.key}:${p.route}`;
                    const decided = decisions[key];
                    return (
                      <tr key={key} style={decided === "reject" ? { opacity: 0.45 } : undefined}>
                        <td>
                          <strong>{p.route}</strong>
                          {p.depot_source !== "route_code" && (
                            <span
                              title="Operating depot inferred by proximity, not stated in BMTC's data"
                              style={{ marginLeft: 6, fontSize: "0.7rem", color: "var(--text-3)" }}
                            >
                              ~
                            </span>
                          )}
                        </td>
                        <td>{num(p.trips)}</td>
                        <td>{p.buses_scheduled}</td>
                        <td>{p.buses_floor}</td>
                        <td style={{ color: "#10b981", fontWeight: 700 }}>−{p.buses_released}</td>
                        <td className="text-muted">{p.dead_km === null ? "—" : num(Math.round(p.dead_km))}</td>
                        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          {decided ? (
                            <span className={`badge ${decided === "approve" ? "badge-success" : ""}`}>
                              {decided === "approve" ? "✓ Approved" : "Rejected"}
                            </span>
                          ) : (
                            <>
                              <button
                                className="bento-btn"
                                disabled={saving === key}
                                onClick={() => decide(p, "approve")}
                                style={{ padding: "4px 10px", fontSize: "0.78rem", borderRadius: 7, background: "#10b981", color: "#fff", border: "none", marginRight: 6 }}
                              >
                                <Check size={13} /> Approve
                              </button>
                              <button
                                className="bento-btn secondary"
                                disabled={saving === key}
                                onClick={() => decide(p, "reject")}
                                style={{ padding: "4px 10px", fontSize: "0.78rem", borderRadius: 7 }}
                              >
                                <X size={13} /> Reject
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {depot.routes_depot_inferred > 0 && (
            <p className="text-muted" style={{ fontSize: "0.78rem", margin: "0.85rem 0 0 0" }}>
              ~ {num(depot.routes_depot_inferred)} of these routes have their operating depot
              inferred by proximity. BMTC's route-to-depot mapping would replace that
              inference and unlock a citywide dead-km figure.
            </p>
          )}
        </>
      )}

      {/* ── Assumptions, stated openly ───────────────────────────────────── */}
      <details style={{ marginTop: "1.5rem" }}>
        <summary style={{ cursor: "pointer", fontSize: "0.83rem", color: "var(--text-2)" }}>
          Assumptions & limits
        </summary>
        <div style={{ paddingTop: "0.75rem", fontSize: "0.8rem", color: "var(--text-3)", lineHeight: 1.6 }}>
          <div style={{ display: "flex", gap: "1.25rem", flexWrap: "wrap", marginBottom: "0.6rem" }}>
            <span>Speed {plan.assumptions.average_speed_kmph} km/h</span>
            <span>Dwell {plan.assumptions.dwell_minutes_per_stop} min/stop</span>
            <span>Layover {plan.assumptions.layover_minutes} min</span>
            <span>Deadhead ≤ {plan.assumptions.max_deadhead_km} km</span>
            <span>Circuity {plan.assumptions.circuity_factor}</span>
          </div>
          {(plan.caveats || []).map((c: string, i: number) => (
            <p key={i} style={{ margin: "0 0 0.4rem 0" }}>• {c}</p>
          ))}
          <p style={{ margin: 0 }}>Source: {plan.source}</p>
        </div>
      </details>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  accent,
  good,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: boolean;
  good?: boolean;
}) {
  return (
    <div
      style={{
        padding: "0.9rem 1rem",
        borderRadius: 12,
        background: "var(--surface-strong)",
        border: `1px solid ${good ? "#10b98155" : accent ? "var(--line-strong)" : "var(--line-strong)"}`,
      }}
    >
      <div
        style={{
          fontSize: "1.45rem",
          fontWeight: 800,
          lineHeight: 1.1,
          color: good ? "#10b981" : accent ? "var(--accent, #00e5c8)" : "var(--text)",
        }}
      >
        {value}
      </div>
      <div style={{ fontSize: "0.76rem", fontWeight: 600, marginTop: 4 }}>{label}</div>
      {hint && <div style={{ fontSize: "0.7rem", color: "var(--text-3)", marginTop: 2 }}>{hint}</div>}
    </div>
  );
}
