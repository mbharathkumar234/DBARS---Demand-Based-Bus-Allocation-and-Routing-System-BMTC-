import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Vote, Map, Navigation, BarChart3, Star, Bell, Truck, ScanLine } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { useLanguage } from "../contexts/LanguageContext";
import { apiFetch } from "../lib/apiClient";
import { NearestMetroPanel } from "../components/NearestMetroPanel";

export default function CommuterDashboard() {
  const { user, token } = useAuth();
  const { t } = useLanguage();
  const [myVotes, setMyVotes] = useState<any[]>([]);
  const [notifications, setNotifications] = useState<any[]>([]);

  useEffect(() => {
    if (!token) return;
    apiFetch(`/votes/my?limit=5`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((d) => setMyVotes(d.votes || []))
      .catch(() => {});

    // A GET /tracking/favorites call used to sit here: it awaited the response
    // and then discarded it -- no setState, nothing rendered. Removed rather
    // than left in place, since it only cost a request per dashboard load.
    // The favorites endpoints themselves still work and are still unused by
    // any UI.
  }, [token]);

  const quickActions = [
    { to: "/vote", icon: <Vote size={24} />, label: t("nav.vote"), color: "#f43f5e", desc: "Vote for new bus routes" },
    { to: "/predict", icon: <Map size={24} />, label: t("nav.predict"), color: "#6366f1", desc: "Find best bus connection" },
    { to: "/track", icon: <Navigation size={24} />, label: t("nav.track"), color: "#10b981", desc: "Simulated bus tracking demo" },
  ];

  return (
    <div className="dashboard-page">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        {/* Welcome */}
        <div className="dashboard-welcome">
          <h1>Welcome, {user?.name || "Commuter"} 👋</h1>
          <p className="text-muted">What would you like to do today?</p>
        </div>

        {/* Quick Actions */}
        <div className="quick-actions-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.25rem', marginBottom: '2rem' }}>
          {quickActions.map((a, i) => (
            <Link to={a.to} key={i} className="quick-action-card bento-card" style={{ textDecoration: 'none', color: 'inherit' }}>
              <div className="qa-icon" style={{ color: a.color }}>{a.icon}</div>
              <div>
                <h3 style={{ fontSize: '1.05rem', fontWeight: 700, margin: '0 0 0.25rem 0' }}>{a.label}</h3>
                <p className="text-muted" style={{ fontSize: '0.82rem', margin: 0 }}>{a.desc}</p>
              </div>
            </Link>
          ))}
        </div>

        {/* Namma Metro Station & Map Finder Widget */}
        <NearestMetroPanel
          initialStop="Marathahalli"
          title="🚈 Nearest Namma Metro Station & 2025 Map"
          showSearch={true}
        />

        {/* Recent Votes */}
        <div className="dashboard-section bento-card">
          <div className="justify-between items-center flex mb-4">
            <h2 className="bento-title" style={{ marginBottom: 0 }}>
              <Vote size={20} /> {t("vote.my_votes")}
            </h2>
            <Link to="/vote" className="secondary-button" style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem' }}>
              View all →
            </Link>
          </div>

          {myVotes.length === 0 ? (
            <div className="empty-state">
              <p>No votes yet. <Link to="/vote" className="text-accent">Cast your first vote!</Link></p>
            </div>
          ) : (
            <div className="vote-history-list">
              {myVotes.map((v: any) => (
                <div key={v.id} className="vote-history-item">
                  <div className="vote-route">
                    <span>{v.current_stop}</span>
                    <span className="vote-arrow">→</span>
                    <span>{v.destination}</span>
                  </div>
                  <div className="vote-meta">
                    <span className="vote-time-badge">{v.time_preference}</span>
                    {v.is_flagged && <span className="badge badge-danger">Flagged</span>}
                    <Link
                      to={`/predict?from=${encodeURIComponent(v.current_stop)}&to=${encodeURIComponent(v.destination)}`}
                      className="primary-button"
                      style={{ padding: '0.4rem 0.8rem', fontSize: '0.8rem', height: 'auto' }}
                    >
                      <Map size={14} /> View Route
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}