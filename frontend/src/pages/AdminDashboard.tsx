import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { BarChart3, Users, Vote, Zap, AlertTriangle, Clock, RefreshCw, Shield, Maximize2, Minimize2, ArrowLeft } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line, AreaChart, Area } from "recharts";
import { useAuth } from "../contexts/AuthContext";
import { useLanguage } from "../contexts/LanguageContext";
import { SearchInputWithHistory } from "../components/SearchInputWithHistory";
import BlockingSummaryCard from "../components/BlockingSummaryCard";
import toast from "react-hot-toast";
import { apiFetch } from "../lib/apiClient";

const COLORS = ["#6366f1", "#f43f5e", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"];

export default function AdminDashboard() {
  const { token } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState<any>(null);
  const [fraud, setFraud] = useState<any>(null);
  const [users, setUsers] = useState<any>(null);
  const [userSearch, setUserSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<"overview" | "users" | "fraud">("overview");
  const [expandedChart, setExpandedChart] = useState<string | null>(null);

  const getChartStyle = (id: string) => {
    if (expandedChart === id) {
      return { position: 'fixed' as const, top: 40, left: 40, right: 40, bottom: 40, zIndex: 9999, padding: '3rem', margin: 0 };
    }
    return { padding: '1.5rem', position: 'relative' as const };
  };

  const headers = { Authorization: `Bearer ${token}` };

  const fetchUsers = async (searchQuery: string) => {
    try {
      const res = await apiFetch(`/admin/users?limit=50&search=${encodeURIComponent(searchQuery)}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setUsers(data);
      }
    } catch (err) {
      console.error("Failed to search users:", err);
    }
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const [dashRes, fraudRes, usersRes] = await Promise.all([
        apiFetch(`/admin/dashboard`, { headers }),
        apiFetch(`/admin/fraud/alerts`, { headers }),
        apiFetch(`/admin/users?limit=50`, { headers }),
      ]);
      if (dashRes.ok) setDashboard(await dashRes.json());
      if (fraudRes.ok) setFraud(await fraudRes.json());
      if (usersRes.ok) setUsers(await usersRes.json());
    } catch (err) {
      toast.error("Failed to load backend admin metrics");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [token]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (token) fetchUsers(userSearch);
    }, 300);
    return () => clearTimeout(timer);
  }, [userSearch, token]);

  const retrain = async () => {
    try {
      toast.loading("Spinning up model retraining...", { id: "retrain" });
      await apiFetch(`/train`, { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify({ force: true }) });
      toast.success("Predictor model retrained successfully!", { id: "retrain" });
    } catch { toast.error("Failed to retrain model", { id: "retrain" }); }
  };

  if (loading) return <div className="page-container"><div className="page-loader">{t("common.loading")}</div></div>;

  const kpi = dashboard?.kpi || {
    total_commuters: 0,
    active_today: 0,
    total_votes_30d: 0,
    prediction_accuracy_pct: 0,
    flagged_votes: 0,
    avg_response_ms: 0,
  };

  const topRoutes = (dashboard?.top_routes || []).slice(0, 7).map((r: any) => ({ name: `${r.current_stop}→${r.destination}`.slice(0, 25), votes: r.votes }));
  const hoursData = (dashboard?.votes_by_hour || []).map((h: any) => ({ hour: `${h.hour}:00`, votes: h.count }));
  const trendData = (dashboard?.daily_trend || []).map((d: any) => ({ date: d.day?.slice(5), votes: d.count }));
  const langData = Object.entries(dashboard?.language_distribution || {}).map(([k, v]) => ({ name: k.toUpperCase(), value: v as number }));

  return (
    <div className="page-container">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="admin-page">
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
          <BarChart3 size={24} className="text-accent" style={{ flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <h1 className="bento-title" style={{ margin: 0 }}>{t("admin.title")}</h1>
            <p className="text-muted" style={{ margin: 0, fontSize: '0.9rem' }}>Deep dive into fleet operations and commuter demand</p>
          </div>
          <button className="bento-btn" onClick={loadData} style={{ marginLeft: "auto" }}>
            <RefreshCw size={14} /> Sync Data
          </button>
        </div>

        {/* Tab navigation */}
        <div className="admin-tabs">
          <button className={`tab-btn ${activeTab === "overview" ? "active" : ""}`} onClick={() => setActiveTab("overview")}>
            <BarChart3 size={14} /> Overview
          </button>
          <button className={`tab-btn ${activeTab === "users" ? "active" : ""}`} onClick={() => setActiveTab("users")}>
            <Users size={14} /> {t("admin.users")}
          </button>
          <button className={`tab-btn ${activeTab === "fraud" ? "active" : ""}`} onClick={() => setActiveTab("fraud")}>
            <Shield size={14} /> {t("admin.fraud")}
          </button>
        </div>

        {activeTab === "overview" && (
          <>
            {/* KPI Cards */}
            <div className="kpi-grid">
              <div className="kpi-card bento-card"><Users size={20} /><div><span className="kpi-value">{kpi.total_commuters}</span><span className="kpi-label">{t("admin.total_commuters")}</span></div></div>
              <div className="kpi-card bento-card"><Zap size={20} /><div><span className="kpi-value">{kpi.active_today}</span><span className="kpi-label">{t("admin.active_today")}</span></div></div>
              <div className="kpi-card bento-card"><Vote size={20} /><div><span className="kpi-value">{kpi.total_votes_30d}</span><span className="kpi-label">{t("admin.total_votes")}</span></div></div>
              <div className="kpi-card bento-card"><BarChart3 size={20} /><div><span className="kpi-value">{kpi.prediction_accuracy_pct}%</span><span className="kpi-label">{t("admin.accuracy")}</span></div></div>
              <div className="kpi-card kpi-warn bento-card"><AlertTriangle size={20} /><div><span className="kpi-value">{kpi.flagged_votes}</span><span className="kpi-label">{t("admin.flagged")}</span></div></div>
              <div className="kpi-card bento-card"><Clock size={20} /><div><span className="kpi-value">{kpi.avg_response_ms}ms</span><span className="kpi-label">{t("admin.avg_response")}</span></div></div>
            </div>

            {/* Citywide fleet blocking. Reads only the published timetable, so
                unlike the vote/user KPIs above it renders with or without a
                database connection. */}
            <BlockingSummaryCard token={token} />

            {expandedChart && <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', zIndex: 9998, backdropFilter: 'blur(5px)' }} onClick={() => setExpandedChart(null)} />}
            
            {/* Charts */}
            <div className="bento-grid">
              <div className="chart-card bento-card" style={getChartStyle('top_routes')}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h3 className="bento-title" style={{ fontSize: '1.1rem', margin: 0 }}>{t("admin.top_routes")}</h3>
                  <button onClick={() => setExpandedChart(expandedChart === 'top_routes' ? null : 'top_routes')} style={{ background: expandedChart === 'top_routes' ? '#f43f5e' : 'var(--surface-strong)', border: '1px solid var(--line-strong)', borderRadius: '6px', padding: '6px', cursor: 'pointer', color: expandedChart === 'top_routes' ? 'white' : 'var(--text)' }}>
                    {expandedChart === 'top_routes' ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
                  </button>
                </div>
                <ResponsiveContainer width="100%" height={expandedChart === 'top_routes' ? "90%" : 260}>
                  <BarChart data={topRoutes} layout="vertical" margin={{ left: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(0, 229, 200, 0.2)" />
                    <XAxis type="number" stroke="rgba(0, 229, 200, 0.8)" tick={{ fill: expandedChart === 'top_routes' ? '#e2e8f0' : 'var(--text)' }} />
                    <YAxis type="category" dataKey="name" width={140} stroke="rgba(0, 229, 200, 0.8)" tick={{ fontSize: 11, fill: expandedChart === 'top_routes' ? '#e2e8f0' : 'var(--text)' }} />
                    <Tooltip contentStyle={{ background: "rgba(10, 22, 40, 0.9)", border: "1px solid rgba(0,229,200,0.5)", borderRadius: 8, color: '#fff' }} />
                    <Bar dataKey="votes" fill="url(#colorCyan)" radius={[0, 4, 4, 0]} />
                    <defs>
                      <linearGradient id="colorCyan" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="#00e5c8" stopOpacity={0.8}/>
                        <stop offset="100%" stopColor="#a78bfa" stopOpacity={0.8}/>
                      </linearGradient>
                    </defs>
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="chart-card bento-card" style={getChartStyle('votes_by_hour')}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h3 className="bento-title" style={{ fontSize: '1.1rem', margin: 0 }}>{t("admin.votes_by_hour")}</h3>
                  <button onClick={() => setExpandedChart(expandedChart === 'votes_by_hour' ? null : 'votes_by_hour')} style={{ background: expandedChart === 'votes_by_hour' ? '#f43f5e' : 'var(--surface-strong)', border: '1px solid var(--line-strong)', borderRadius: '6px', padding: '6px', cursor: 'pointer', color: expandedChart === 'votes_by_hour' ? 'white' : 'var(--text)' }}>
                    {expandedChart === 'votes_by_hour' ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
                  </button>
                </div>
                <ResponsiveContainer width="100%" height={expandedChart === 'votes_by_hour' ? "90%" : 260}>
                  <AreaChart data={hoursData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(0, 229, 200, 0.2)" />
                    <XAxis dataKey="hour" stroke="rgba(0, 229, 200, 0.8)" tick={{ fontSize: 10, fill: expandedChart === 'votes_by_hour' ? '#e2e8f0' : 'var(--text)' }} />
                    <YAxis stroke="rgba(0, 229, 200, 0.8)" tick={{ fill: expandedChart === 'votes_by_hour' ? '#e2e8f0' : 'var(--text)' }} />
                    <Tooltip contentStyle={{ background: "rgba(10, 22, 40, 0.9)", border: "1px solid rgba(0,229,200,0.5)", borderRadius: 8, color: '#fff' }} />
                    <Area type="monotone" dataKey="votes" stroke="#f43f5e" fill="#f43f5e" fillOpacity={0.3} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              <div className="chart-card bento-card" style={getChartStyle('daily_trend')}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h3 className="bento-title" style={{ fontSize: '1.1rem', margin: 0 }}>{t("admin.daily_trend")}</h3>
                  <button onClick={() => setExpandedChart(expandedChart === 'daily_trend' ? null : 'daily_trend')} style={{ background: expandedChart === 'daily_trend' ? '#f43f5e' : 'var(--surface-strong)', border: '1px solid var(--line-strong)', borderRadius: '6px', padding: '6px', cursor: 'pointer', color: expandedChart === 'daily_trend' ? 'white' : 'var(--text)' }}>
                    {expandedChart === 'daily_trend' ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
                  </button>
                </div>
                <ResponsiveContainer width="100%" height={expandedChart === 'daily_trend' ? "90%" : 260}>
                  <LineChart data={trendData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(0, 229, 200, 0.2)" />
                    <XAxis dataKey="date" stroke="rgba(0, 229, 200, 0.8)" tick={{ fill: expandedChart === 'daily_trend' ? '#e2e8f0' : 'var(--text)' }} />
                    <YAxis stroke="rgba(0, 229, 200, 0.8)" tick={{ fill: expandedChart === 'daily_trend' ? '#e2e8f0' : 'var(--text)' }} />
                    <Tooltip contentStyle={{ background: "rgba(10, 22, 40, 0.9)", border: "1px solid rgba(0,229,200,0.5)", borderRadius: 8, color: '#fff' }} />
                    <Line type="monotone" dataKey="votes" stroke="#00e5c8" strokeWidth={3} dot={{ r: 4, fill: '#00e5c8', stroke: '#fff', strokeWidth: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              <div className="chart-card bento-card" style={getChartStyle('languages')}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h3 className="bento-title" style={{ fontSize: '1.1rem', margin: 0 }}>{t("admin.languages")}</h3>
                  <button onClick={() => setExpandedChart(expandedChart === 'languages' ? null : 'languages')} style={{ background: expandedChart === 'languages' ? '#f43f5e' : 'var(--surface-strong)', border: '1px solid var(--line-strong)', borderRadius: '6px', padding: '6px', cursor: 'pointer', color: expandedChart === 'languages' ? 'white' : 'var(--text)' }}>
                    {expandedChart === 'languages' ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
                  </button>
                </div>
                <ResponsiveContainer width="100%" height={expandedChart === 'languages' ? "90%" : 260}>
                  <PieChart>
                    <Pie data={langData} cx="50%" cy="50%" innerRadius={50} outerRadius={90} paddingAngle={4} dataKey="value" label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ""} ${((percent ?? 0) * 100).toFixed(0)}%`}>
                      {langData.map((_: any, i: number) => (<Cell key={i} fill={COLORS[i % COLORS.length]} />))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Retrain button */}
            <div className="bento-card" style={{ textAlign: "center", padding: "2.5rem", marginTop: "2rem" }}>
              <h3 className="bento-title">{t("admin.model")}</h3>
              <p className="text-muted">Retrain the hybrid ML prediction engine with latest route data</p>
              <button className="bento-btn" onClick={retrain} style={{ marginTop: "1rem" }}>
                <RefreshCw size={16} /> {t("admin.retrain")}
              </button>
            </div>
          </>
        )}

        {activeTab === "users" && (
          <div className="bento-card" style={{ padding: "2rem" }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h3 className="bento-title" style={{ fontSize: '1.2rem', margin: 0 }}>{t("admin.users")} ({users?.total || 0})</h3>
              <div style={{ width: '300px' }}>
                <SearchInputWithHistory
                  storageKey="bmtc_history_admin_users"
                  value={userSearch}
                  onChange={setUserSearch}
                  placeholder="Search by name or email..."
                />
              </div>
            </div>
            <div className="admin-table-container">
              <table className="admin-table">
                <thead>
                  <tr><th>Name</th><th>Email</th><th>Role</th><th>Language</th><th>Reliability</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {(users?.users || []).map((u: any) => (
                    <tr key={u.id}>
                      <td>{u.name}</td>
                      <td>{u.email}</td>
                      <td><span className={`role-badge role-${u.role}`}>{u.role}</span></td>
                      <td>{u.preferred_lang?.toUpperCase()}</td>
                      <td><span style={{ color: u.reliability < 0.7 ? "#ef4444" : "#10b981" }}>{(u.reliability * 100).toFixed(0)}%</span></td>
                      <td><span className={`badge ${u.is_active ? "badge-success" : "badge-danger"}`}>{u.is_active ? "Active" : "Suspended"}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === "fraud" && (
          <div className="fraud-section">
            <div className="bento-card" style={{ padding: "2rem", marginBottom: "2rem" }}>
              <h3 className="bento-title" style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}><AlertTriangle size={18} /> Flagged Votes ({fraud?.flagged_votes?.length || 0})</h3>
              {(fraud?.flagged_votes || []).length === 0 ? (
                <p className="text-muted">No flagged votes — all clear! ✅</p>
              ) : (
                <div className="admin-table-container">
                  <table className="admin-table">
                    <thead><tr><th>User</th><th>Route</th><th>IP</th><th>Time</th></tr></thead>
                    <tbody>
                      {(fraud?.flagged_votes || []).map((v: any) => (
                        <tr key={v.id}>
                          <td>{v.name} ({v.email})</td>
                          <td>{v.current_stop} → {v.destination}</td>
                          <td>{v.ip_address}</td>
                          <td>{v.created_at?.slice(0, 16)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            {(fraud?.suspicious_users || []).length > 0 && (
              <div className="bento-card" style={{ padding: "2rem" }}>
                <h3 className="bento-title" style={{ fontSize: '1.2rem', display: 'flex', alignItems: 'center', gap: '8px' }}><Shield size={18} /> Low Reliability Users</h3>
                <div className="admin-table-container">
                  <table className="admin-table">
                    <thead><tr><th>Name</th><th>Email</th><th>Reliability</th></tr></thead>
                    <tbody>
                      {(fraud?.suspicious_users || []).map((u: any) => (
                        <tr key={u.id}>
                          <td>{u.name}</td><td>{u.email}</td>
                          <td style={{ color: "#ef4444" }}>{(u.reliability * 100).toFixed(0)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </motion.div>
    </div>
  );
}
