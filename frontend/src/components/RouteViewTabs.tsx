import { useMemo, useState } from "react";
import { Repeat, Route as RouteIcon } from "lucide-react";
import type { TransferSuggestion } from "../types/api";

type Props = {
  fewestTransfers: TransferSuggestion[];
  leastDistance: TransferSuggestion[];
};

type TabKey = "transfers" | "distance";

const TABS: { key: TabKey; label: string; hint: string }[] = [
  {
    key: "transfers",
    label: "Route with few Transfers",
    hint: "Fewest bus changes, whatever the distance or time",
  },
  {
    key: "distance",
    label: "Route with least Travelling Distance and Time",
    hint: "Shortest and quickest, whatever the number of changes",
  },
];

function fmtDuration(minutes?: number | null): string {
  if (!minutes || minutes <= 0) return "—";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h}h ${m}m` : `${m} min`;
}

function fmtChanges(transfers?: number | null): string {
  const n = transfers ?? 0;
  if (n === 0) return "Direct";
  return `${n} change${n > 1 ? "s" : ""}`;
}

/**
 * The two readings of one candidate set.
 *
 * They genuinely disagree, and showing only one hid the trade-off: the journey
 * with the fewest changes is often the longer ride, while the shortest ride
 * often needs an extra bus.
 *
 * Laid out as a real grid rather than a flex row of icon+number pairs. In the
 * flex version the figures wrapped under their own icons and no column lined
 * up with the row above it, which made four numbers per row unreadable.
 */
export function RouteViewTabs({ fewestTransfers, leastDistance }: Props) {
  const [tab, setTab] = useState<TabKey>("transfers");
  const options = tab === "transfers" ? fewestTransfers : leastDistance;

  // Only worth calling out the trade-off when the two views actually disagree.
  const tradeOff = useMemo(() => {
    const a = fewestTransfers?.[0];
    const b = leastDistance?.[0];
    if (!a || !b || a.bus_chain === b.bus_chain) return null;
    const aKm = a.total_distance_km ?? null;
    const bKm = b.total_distance_km ?? null;
    if (aKm == null || bKm == null || bKm >= aKm) return null;
    const saved = Math.round(((aKm - bKm) / aKm) * 100);
    if (saved < 5) return null;
    return { saved, aKm, bKm, extra: (b.transfers ?? 0) - (a.transfers ?? 0) };
  }, [fewestTransfers, leastDistance]);

  if (!fewestTransfers?.length && !leastDistance?.length) return null;

  return (
    <div className="bento-card rvt" style={{ padding: "1.5rem", marginTop: "2rem" }}>
      <style>{`
        .rvt-grid {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 96px 76px 92px 86px;
          align-items: center;
          gap: 0 0.75rem;
        }
        .rvt-num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
        .rvt-head {
          font-size: 0.68rem; letter-spacing: 0.06em; text-transform: uppercase;
          color: var(--muted); font-weight: 700;
          padding: 0 0.9rem 0.5rem;
        }
        .rvt-row {
          padding: 0.85rem 0.9rem; border-radius: 12px;
          border: 1px solid var(--line); background: transparent;
        }
        .rvt-row.is-best { border-color: var(--brand); background: var(--surface-2); }
        .rvt-chain {
          font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 0.86rem; font-weight: 700; overflow-wrap: anywhere;
        }
        @media (max-width: 760px) {
          .rvt-grid { grid-template-columns: 1fr 1fr; gap: 0.4rem 0.75rem; }
          .rvt-main { grid-column: 1 / -1; }
          .rvt-num { text-align: left; }
          .rvt-head { display: none; }
        }
      `}</style>

      {/* Tabs */}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        {TABS.map((t) => {
          const active = t.key === tab;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              style={{
                display: "inline-flex", alignItems: "center", gap: "8px",
                padding: "0.6rem 1.05rem", borderRadius: "12px", cursor: "pointer",
                fontSize: "0.85rem", fontWeight: 600, lineHeight: 1.2,
                border: active ? "1px solid transparent" : "1px solid var(--line-strong)",
                background: active ? "var(--gradient-brand)" : "var(--surface-strong)",
                color: active ? "#fff" : "var(--text)",
                transition: "all 0.15s ease",
              }}
            >
              {t.key === "transfers" ? <Repeat size={15} /> : <RouteIcon size={15} />}
              {t.label}
            </button>
          );
        })}
      </div>

      <p className="text-muted" style={{ fontSize: "0.82rem", margin: "0.7rem 0 0" }}>
        {TABS.find((t) => t.key === tab)?.hint}
      </p>

      {tradeOff && (
        <div
          style={{
            padding: "0.65rem 0.85rem", margin: "1rem 0 0", borderRadius: "10px",
            background: "var(--surface-2)", border: "1px solid var(--line)",
            fontSize: "0.8rem", lineHeight: 1.5,
          }}
        >
          Shortest ride saves <strong>{tradeOff.saved}%</strong> distance
          {" "}({tradeOff.bKm} km vs {tradeOff.aKm} km)
          {tradeOff.extra > 0 && (
            <> but needs <strong>{tradeOff.extra} more change{tradeOff.extra > 1 ? "s" : ""}</strong></>
          )}.
        </div>
      )}

      {!options?.length ? (
        <p className="text-muted" style={{ fontSize: "0.85rem", margin: "1rem 0 0" }}>
          No option available for this view.
        </p>
      ) : (
        <div style={{ marginTop: "1.1rem" }}>
          <div className="rvt-grid rvt-head" aria-hidden="true">
            <span>Route</span>
            <span className="rvt-num">Changes</span>
            <span className="rvt-num">Stops</span>
            <span className="rvt-num">Distance</span>
            <span className="rvt-num">Time</span>
          </div>

          <div style={{ display: "grid", gap: "0.5rem" }}>
            {options.slice(0, 5).map((opt, idx) => (
              <div
                key={`${opt.bus_chain}-${idx}`}
                className={`rvt-grid rvt-row${idx === 0 ? " is-best" : ""}`}
              >
                <div className="rvt-main" style={{ minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "baseline", gap: "0.6rem", flexWrap: "wrap" }}>
                    <span className="rvt-chain">{opt.bus_chain}</span>
                    {idx === 0 && (
                      <span style={{
                        fontSize: "0.64rem", fontWeight: 800, letterSpacing: "0.06em",
                        color: "var(--brand)", textTransform: "uppercase",
                      }}>
                        Best
                      </span>
                    )}
                  </div>
                  {opt.transfer_stops?.length > 0 && (
                    <div className="text-muted" style={{ fontSize: "0.75rem", marginTop: "0.3rem" }}>
                      Change at {opt.transfer_stops.join(", ")}
                    </div>
                  )}
                </div>

                <span className="rvt-num" style={{ fontSize: "0.82rem", fontWeight: 600 }}>
                  {fmtChanges(opt.transfers)}
                </span>
                <span className="rvt-num text-muted" style={{ fontSize: "0.82rem" }}>
                  {opt.total_stops ?? "—"}
                </span>
                <span className="rvt-num" style={{ fontSize: "0.82rem", fontWeight: 600 }}>
                  {opt.total_distance_km != null ? `${opt.total_distance_km} km` : "—"}
                </span>
                <span className="rvt-num" style={{ fontSize: "0.82rem", fontWeight: 600 }}>
                  {fmtDuration(opt.duration_minutes)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-muted" style={{ fontSize: "0.72rem", margin: "1rem 0 0", lineHeight: 1.5 }}>
        Times are estimated from route distance plus a fixed waiting allowance per change,
        not from live running data.
      </p>
    </div>
  );
}
