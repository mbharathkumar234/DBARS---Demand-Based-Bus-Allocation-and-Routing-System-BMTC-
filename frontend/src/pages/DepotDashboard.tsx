import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Truck, BarChart3, Route, RefreshCw, Maximize2, Minimize2, ArrowLeft } from "lucide-react";
import { SearchInputWithHistory } from "../components/SearchInputWithHistory";
import BlockingPanel from "../components/BlockingPanel";
import ScenarioConsole from "../components/ScenarioConsole";
import CrewPanel from "../components/CrewPanel";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useAuth } from "../contexts/AuthContext";
import { useLanguage } from "../contexts/LanguageContext";
import { apiFetch } from "../lib/apiClient";

export default function DepotDashboard() {
  const { token } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [demand, setDemand] = useState<any[]>([]);
  const [buses, setBuses] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busSearch, setBusSearch] = useState("");
  const [expandedChart, setExpandedChart] = useState<string | null>(null);

  const getChartStyle = (id: string) => {
    if (expandedChart === id) {
      return { position: 'fixed' as const, top: 40, left: 40, right: 40, bottom: 40, zIndex: 9999, padding: '3rem', margin: 0 };
    }
    return { padding: '2rem', position: 'relative' as const };
  };

  const [dispatchData, setDispatchData] = useState<any>(null);
  const [deploying, setDeploying] = useState<string | null>(null);

  const fetchRecommendations = () => {
    const headers = { Authorization: `Bearer ${token}` };
    apiFetch(`/depot/dispatch-recommendations`, { headers })
      .then(async (r) => (r.ok ? r.json() : null))
      .then((data) => { if (data) setDispatchData(data); })
      .catch(() => { });
  };

  useEffect(() => {
    const headers = { Authorization: `Bearer ${token}` };

    Promise.allSettled([
      apiFetch(`/votes/aggregate?days=7`, { headers }).then(async (r) => (r.ok ? r.json() : null)),
      apiFetch(`/tracking/buses`, { headers }).then(async (r) => (r.ok ? r.json() : null)),
      apiFetch(`/depot/dispatch-recommendations`, { headers }).then(async (r) => (r.ok ? r.json() : null)),
    ])
      .then(([demandRes, fleetRes, dispatchRes]) => {
        if (demandRes.status === "fulfilled" && demandRes.value) {
          setDemand((demandRes.value.demand || []).slice(0, 15));
        }
        if (fleetRes.status === "fulfilled" && fleetRes.value) {
          setBuses(fleetRes.value.buses || []);
        }
        if (dispatchRes.status === "fulfilled" && dispatchRes.value) {
          setDispatchData(dispatchRes.value);
        }
      })
      .finally(() => setLoading(false));
  }, [token]);

  const handleDeployBus = async (routeNumber: string) => {
    setDeploying(routeNumber);
    try {
      await apiFetch(`/depot/deploy-bus`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ route_number: routeNumber })
      });
      fetchRecommendations();
    } catch (e) {
      console.error(e);
    } finally {
      setDeploying(null);
    }
  };

  if (loading) return <div className="page-container"><div className="page-loader">{t("common.loading")}</div></div>;

  const demandChart = demand.map((d) => ({
    name: `${d.current_stop}→${d.destination}`.slice(0, 25),
    votes: d.vote_count,
    voters: d.unique_voters,
  }));

  // Fleet overview
  const avgOccupancy = buses.length ? (buses.reduce((sum, b) => sum + b.occupancy_pct, 0) / buses.length).toFixed(0) : 0;
  const avgSpeed = buses.length ? (buses.reduce((sum, b) => sum + b.speed_kmh, 0) / buses.length).toFixed(1) : 0;
  const highOccupancy = buses.filter((b) => b.occupancy_pct > 75).length;

  return (
    <div className="page-container">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="depot-page">
        <div className="page-header bento-card" style={{ padding: '1.25rem 2rem', marginBottom: '2rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <button
            type="button"
            onClick={() => navigate(-1)}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface-strong)', border: '1px solid var(--line-strong)', borderRadius: '50%', width: '38px', height: '38px', cursor: 'pointer', color: 'var(--text)', flexShrink: 0, transition: 'background 0.15s' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-sunken)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'var(--surface-strong)')}
            title="Go Back"
          >
            <ArrowLeft size={18} />
          </button>
          <Truck size={24} className="text-accent" style={{ flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <h1 className="bento-title" style={{ margin: 0 }}>{t("depot.title")}</h1>
            <p className="text-muted" style={{ margin: 0, fontSize: '0.9rem' }}>Live fleet tracker, AI route dispatch engine, and EV battery metrics</p>
          </div>
        </div>

        {/* Fleet KPIs */}
        <div className="kpi-grid">
          <div className="kpi-card bento-card">
            <Truck size={20} />
            <div><span className="kpi-value">{buses.length}</span><span className="kpi-label">Active Buses</span></div>
          </div>
          <div className="kpi-card bento-card">
            <BarChart3 size={20} />
            <div><span className="kpi-value">{avgOccupancy}%</span><span className="kpi-label">Avg Occupancy</span></div>
          </div>
          <div className="kpi-card bento-card">
            <Route size={20} />
            <div><span className="kpi-value">{avgSpeed} km/h</span><span className="kpi-label">Avg Speed</span></div>
          </div>
          <div className="kpi-card kpi-warn bento-card">
            <Truck size={20} />
            <div><span className="kpi-value">{highOccupancy}</span><span className="kpi-label">High Occupancy ({">"}75%)</span></div>
          </div>
        </div>

        {/* Fleet blocking plan. Placed above the vote-driven panel below
            deliberately: this one runs on BMTC's own published timetable and
            needs no database, so it is the panel that still works -- and the
            one worth leading with -- when showing this to BMTC. */}
        <BlockingPanel token={token} />

        {/* The "what if" half of the same engine. Sits directly under the plan
            because the plan establishes the baseline this compares against. */}
        <ScenarioConsole token={token} />

        {/* Crew duties, immediately under the fleet plan on purpose: a re-block
            that saves buses by stretching each one across fourteen hours has
            saved nothing unless a roster can staff it, and seeing both numbers
            on one screen is the whole argument. */}
        <CrewPanel token={token} />

        {/* Dispatch Recommendations, built from real commuter votes */}
        {dispatchData && (
          <div className="bento-card" style={{ padding: '1.75rem', marginBottom: '2rem', background: 'var(--surface-glass)', backdropFilter: 'blur(16px)', border: '1px solid var(--line-strong)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <h3 className="bento-title" style={{ fontSize: '1.25rem', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Route size={20} className="text-accent" /> Route Dispatch Recommendations
                </h3>
                <p className="text-muted" style={{ fontSize: '0.85rem', margin: '4px 0 0 0' }}>
                  Built from real commuter votes over the last {dispatchData.period_days ?? 14} days — each route below is resolved through the live prediction engine, not invented.
                </p>
              </div>
              <button onClick={fetchRecommendations} className="bento-btn secondary" style={{ padding: '6px 12px', fontSize: '0.8rem' }}>
                <RefreshCw size={14} /> Refresh
              </button>
            </div>

            {dispatchData.recommendations && dispatchData.recommendations.length > 0 ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1rem' }}>
                {dispatchData.recommendations.map((rec: any) => {
                  const isDeployed = (dispatchData.deployed_buses || []).some((d: any) => d.route_number === rec.route_number);
                  return (
                    <div key={`${rec.route_number}-${rec.current_stop}-${rec.destination}`} style={{ padding: '1.25rem', borderRadius: '14px', background: 'var(--surface-strong)', border: '1px solid var(--line-strong)', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: '0.75rem' }}>
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                          <span className="bus-badge" style={{ fontSize: '1.1rem', padding: '0.35rem 0.85rem' }}>Route {rec.route_number}</span>
                          <span style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '0.72rem', fontWeight: 800, background: rec.surge_level === 'HIGH' ? '#f43f5e20' : rec.surge_level === 'MEDIUM' ? '#f59e0b20' : '#64748b20', color: rec.surge_level === 'HIGH' ? '#f43f5e' : rec.surge_level === 'MEDIUM' ? '#f59e0b' : '#64748b', border: `1px solid ${rec.surge_level === 'HIGH' ? '#f43f5e50' : rec.surge_level === 'MEDIUM' ? '#f59e0b50' : '#64748b50'}` }}>
                            {rec.surge_level} DEMAND
                          </span>
                        </div>
                        <h4 style={{ margin: '0 0 0.35rem 0', fontSize: '0.95rem' }}>{rec.current_stop} → {rec.destination}</h4>
                        <p className="text-muted" style={{ fontSize: '0.82rem', margin: 0, lineHeight: '1.4' }}>{rec.reason}</p>
                      </div>

                      <div style={{ paddingTop: '0.75rem', borderTop: '1px solid var(--line-strong)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <div style={{ fontSize: '0.78rem', color: 'var(--text-3)' }}>
                          {rec.genuine_vote_count} vote{rec.genuine_vote_count === 1 ? '' : 's'} · {rec.unique_voters} voter{rec.unique_voters === 1 ? '' : 's'}
                        </div>
                        <button
                          className="bento-btn"
                          style={{ padding: '6px 14px', fontSize: '0.82rem', borderRadius: '8px', background: isDeployed ? '#10b981' : 'var(--gradient-brand)', color: 'white', border: 'none', cursor: isDeployed ? 'default' : 'pointer' }}
                          disabled={isDeployed || deploying === rec.route_number}
                          onClick={() => handleDeployBus(rec.route_number)}
                        >
                          {isDeployed ? '✓ Reviewed' : deploying === rec.route_number ? 'Saving...' : 'Mark Reviewed'}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-muted" style={{ fontSize: '0.88rem', margin: 0 }}>
                {dispatchData.note || "No recommendations available yet."}
              </p>
            )}
          </div>
        )}

        {expandedChart && <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9998, backdropFilter: 'blur(5px)' }} onClick={() => setExpandedChart(null)} />}

        {/* 7-Day Demand Forecast Chart */}
        <div className="chart-card bento-card" style={getChartStyle('demand_forecast')}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 className="bento-title" style={{ fontSize: '1.2rem', margin: 0 }}>{t("depot.demand_forecast")} — Top Routes (7-day votes)</h3>
            <button onClick={() => setExpandedChart(expandedChart === 'demand_forecast' ? null : 'demand_forecast')} style={{ background: expandedChart === 'demand_forecast' ? '#f43f5e' : 'var(--surface-strong)', border: '1px solid var(--line-strong)', borderRadius: '6px', padding: '6px', cursor: 'pointer', color: expandedChart === 'demand_forecast' ? 'white' : 'var(--text)' }}>
              {expandedChart === 'demand_forecast' ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
          </div>
          <ResponsiveContainer width="100%" height={expandedChart === 'demand_forecast' ? "90%" : 350}>
            <BarChart data={demandChart} layout="vertical" margin={{ left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0, 229, 200, 0.2)" />
              <XAxis type="number" stroke="rgba(0, 229, 200, 0.8)" tick={{ fill: expandedChart === 'demand_forecast' ? '#e2e8f0' : 'var(--text)' }} />
              <YAxis type="category" dataKey="name" width={160} stroke="rgba(0, 229, 200, 0.8)" tick={{ fontSize: 11, fill: expandedChart === 'demand_forecast' ? '#e2e8f0' : 'var(--text)' }} />
              <Tooltip contentStyle={{ background: "rgba(10, 22, 40, 0.9)", border: "1px solid rgba(0,229,200,0.5)", borderRadius: 8, color: '#fff' }} />
              <Bar dataKey="votes" fill="#00e5c8" radius={[0, 4, 4, 0]} name="Total Votes" />
              <Bar dataKey="voters" fill="#a78bfa" radius={[0, 4, 4, 0]} name="Unique Voters" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Fleet table */}
        <div className="bento-card" style={{ padding: '2rem', marginTop: '2rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 className="bento-title" style={{ fontSize: '1.2rem', margin: 0 }}>{t("depot.fleet")} — Active Bus Fleet</h3>
            <div style={{ width: '300px' }}>
              <SearchInputWithHistory
                storageKey="bmtc_history_depot_fleet"
                value={busSearch}
                onChange={setBusSearch}
                placeholder="Search bus # or direction..."
              />
            </div>
          </div>
          <div className="admin-table-container">
            <table className="admin-table">
              <thead>
                <tr><th>Bus #</th><th>Direction</th><th>Speed</th><th>Occupancy</th><th>Next Stop</th><th>Status</th></tr>
              </thead>
              <tbody>
                {buses
                  .filter(b => b.bus_number.toLowerCase().includes(busSearch.toLowerCase()) || (b.direction || "").toLowerCase().includes(busSearch.toLowerCase()))
                  .slice(0, 20)
                  .map((b, i) => (
                    <tr key={i}>
                      <td><strong>{b.bus_number}</strong></td>
                      <td className="text-muted">{(b.direction || "").slice(0, 40)}</td>
                      <td>{b.speed_kmh} km/h</td>
                      <td>
                        <span style={{ color: b.occupancy_pct > 75 ? "#ef4444" : b.occupancy_pct > 50 ? "#f59e0b" : "#10b981" }}>
                          {b.occupancy_pct}%
                        </span>
                      </td>
                      <td>{b.next_stop}</td>
                      <td><span className="badge badge-success">Running</span></td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      </motion.div>
    </div>
  );
}