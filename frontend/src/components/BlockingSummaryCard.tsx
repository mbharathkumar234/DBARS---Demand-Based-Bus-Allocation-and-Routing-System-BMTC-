import { useEffect, useState } from "react";
import { Layers } from "lucide-react";
import { apiFetch } from "../lib/apiClient";

/**
 * Citywide roll-up of the vehicle blocking plan, for the admin overview.
 *
 * The depot-manager panel (BlockingPanel) is the operational screen where
 * individual re-blocks get approved. This is the corporation-level view: total
 * fleet required, what interlining releases, and which depots hold the biggest
 * share of that saving.
 */
export default function BlockingSummaryCard({ token }: { token: string | null }) {
  const [plan, setPlan] = useState<any>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    if (!token) return;
    apiFetch(`/depot/blocking-plan`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        setPlan(data);
        setState("ready");
      })
      .catch(() => setState("error"));
  }, [token]);

  if (state === "loading") {
    return (
      <div className="bento-card" style={{ padding: "1.75rem", marginTop: "2rem" }}>
        <p className="text-muted" style={{ margin: 0 }}>Computing the fleet blocking plan…</p>
      </div>
    );
  }
  if (state === "error" || !plan?.network) return null;

  const net = plan.network;
  const num = (v: number) => v.toLocaleString("en-IN");
  const pct = ((net.buses_released / net.buses_scheduled) * 100).toFixed(0);

  return (
    <div className="bento-card" style={{ padding: "1.75rem", marginTop: "2rem" }}>
      <div style={{ marginBottom: "1.25rem" }}>
        <h3 className="bento-title" style={{ fontSize: "1.2rem", margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
          <Layers size={20} className="text-accent" /> Fleet Blocking — Citywide
        </h3>
        <p className="text-muted" style={{ fontSize: "0.85rem", margin: "4px 0 0 0" }}>
          From BMTC's published timetable: {num(net.trips)} trips, {num(net.passenger_routes)} passenger
          routes. Same service, scheduled two ways.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "0.85rem", marginBottom: "1.25rem" }}>
        <Cell label="As scheduled" value={num(net.buses_scheduled)} sub="buses" />
        <Cell label="Interlined" value={num(net.buses_interlined)} sub="buses" accent />
        <Cell label="Released" value={num(net.buses_released)} sub={`${pct}% of baseline`} good />
        <Cell label="Hard floor" value={num(net.buses_floor)} sub="unbeatable" />
        <Cell label="Km / bus / day" value={num(net.km_per_bus)} sub="real ≈ 180–200" />
      </div>

      <div className="admin-table-container">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Depot</th>
              <th>Zone</th>
              <th>Routes</th>
              <th>Scheduled</th>
              <th>Interlined</th>
              <th>Released</th>
            </tr>
          </thead>
          <tbody>
            {(plan.depots || []).slice(0, 12).map((d: any) => (
              <tr key={d.key}>
                <td><strong>{d.label}</strong></td>
                <td className="text-muted">{d.zone || "—"}</td>
                <td>{num(d.routes)}</td>
                <td>{num(d.buses_scheduled)}</td>
                <td>{num(d.buses_interlined)}</td>
                <td style={{ color: "#10b981", fontWeight: 700 }}>−{num(d.buses_released)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-muted" style={{ fontSize: "0.76rem", margin: "0.85rem 0 0 0", lineHeight: 1.5 }}>
        Assumes {plan.assumptions.average_speed_kmph} km/h average running speed and{" "}
        {plan.assumptions.layover_minutes} min terminal layover — replace with BMTC's scheduled
        running times before quoting any cost figure. Dead kilometres are reported per depot only
        where the operating depot is stated in the route name.
      </p>
    </div>
  );
}

function Cell({ label, value, sub, accent, good }: { label: string; value: string; sub?: string; accent?: boolean; good?: boolean }) {
  return (
    <div style={{ padding: "0.9rem 1rem", borderRadius: 12, background: "var(--surface-strong)", border: `1px solid ${good ? "#10b98155" : "var(--line-strong)"}` }}>
      <div style={{ fontSize: "1.4rem", fontWeight: 800, lineHeight: 1.1, color: good ? "#10b981" : accent ? "var(--accent, #00e5c8)" : "var(--text)" }}>{value}</div>
      <div style={{ fontSize: "0.76rem", fontWeight: 600, marginTop: 4 }}>{label}</div>
      {sub && <div style={{ fontSize: "0.7rem", color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
