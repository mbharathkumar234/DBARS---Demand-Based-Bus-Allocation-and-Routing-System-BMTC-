import { FormEvent, useState, useEffect } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ArrowLeft, ArrowRightLeft, Loader2, Mic, Search, Sparkles, Navigation, Info, Clock, X, Users } from "lucide-react";
import toast from "react-hot-toast";
import { useLanguage } from "../contexts/LanguageContext";
import { useAuth } from "../contexts/AuthContext";
import { AutocompleteInput } from "../components/AutocompleteInput";
import { NearestMetroPanel } from "../components/NearestMetroPanel";
import { SafetyPanel } from "../components/SafetyPanel";
import { VoiceButton } from "../components/VoiceButton";
import { parseRouteQuery } from "../utils/parseRouteQuery";
import { useSearchHistory } from "../hooks/useSearchHistory";
import { api } from "../services/api";
import { apiFetch } from "../lib/apiClient";
import { RouteMap } from "../components/RouteMap";
import type { PredictionResponse } from "../types/api";

function RouteStopsPanel({ routePath, fromStop, toStop, busNumber }: {
  routePath: string[];
  fromStop: string;
  toStop: string;
  busNumber: string;
}) {
  if (!routePath || routePath.length === 0) {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-muted)', fontSize: '0.9rem', textAlign: 'center' }}>
        No stop data available for this route.
      </div>
    );
  }

  const boardIdx = routePath.findIndex(s => s === fromStop);
  const alightIdx = routePath.findIndex(s => s === toStop);

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.28, ease: 'easeInOut' }}
      style={{ overflow: 'hidden' }}
    >
      <div style={{
        marginTop: '1.25rem',
        background: 'var(--surface-sunken)',
        border: '1px solid var(--line-strong)',
        borderRadius: '14px',
        overflow: 'hidden'
      }}>
        {/* Header */}
        <div style={{
          padding: '0.85rem 1.25rem',
          borderBottom: '1px solid var(--line-strong)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--surface-strong)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1rem' }}>🚏</span>
            <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>
              All Stops — Bus {busNumber}
            </span>
          </div>
          <span style={{
            background: 'var(--gradient-brand-subtle)',
            border: '1px solid var(--brand)',
            color: 'var(--brand-strong)',
            padding: '2px 10px',
            borderRadius: '20px',
            fontSize: '0.8rem',
            fontWeight: 700
          }}>
            {routePath.length} stops
          </span>
        </div>

        {/* Stop list */}
        <div style={{
          maxHeight: '360px',
          overflowY: 'auto',
          padding: '0.75rem 1.25rem'
        }}>
          {routePath.map((stop, idx) => {
            const isBoard = idx === boardIdx;
            const isAlight = idx === alightIdx;
            const isInRange = boardIdx >= 0 && alightIdx >= 0 && idx >= Math.min(boardIdx, alightIdx) && idx <= Math.max(boardIdx, alightIdx);
            const isFirst = idx === 0;
            const isLast = idx === routePath.length - 1;

            let dotColor = 'var(--line-strong)';
            let dotSize = '10px';
            if (isBoard) { dotColor = '#10b981'; dotSize = '14px'; }
            else if (isAlight) { dotColor = '#ef4444'; dotSize = '14px'; }
            else if (isInRange) { dotColor = 'var(--brand)'; dotSize = '8px'; }

            return (
              <div key={idx} style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', position: 'relative' }}>
                {/* Rail line */}
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '14px', flexShrink: 0 }}>
                  {!isFirst && (
                    <div style={{
                      width: '2px',
                      height: '12px',
                      background: isInRange ? 'var(--brand)' : 'var(--line-subtle)',
                      flexShrink: 0
                    }} />
                  )}
                  <div style={{
                    width: dotSize,
                    height: dotSize,
                    borderRadius: '50%',
                    background: dotColor,
                    boxShadow: (isBoard || isAlight) ? `0 0 8px ${dotColor}` : 'none',
                    border: (isBoard || isAlight) ? '2px solid white' : 'none',
                    flexShrink: 0,
                    transition: 'all 0.2s'
                  }} />
                  {!isLast && (
                    <div style={{
                      width: '2px',
                      flex: 1,
                      minHeight: '12px',
                      background: isInRange && idx < Math.max(boardIdx, alightIdx) ? 'var(--brand)' : 'var(--line-subtle)'
                    }} />
                  )}
                </div>

                {/* Stop label */}
                <div style={{
                  paddingTop: '6px',
                  paddingBottom: '10px',
                  flex: 1
                }}>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    flexWrap: 'wrap'
                  }}>
                    <span style={{
                      fontSize: isBoard || isAlight ? '0.95rem' : '0.88rem',
                      fontWeight: isBoard || isAlight ? 700 : isInRange ? 500 : 400,
                      color: isBoard ? '#10b981' : isAlight ? '#ef4444' : isInRange ? 'var(--text)' : 'var(--text-muted)'
                    }}>
                      {stop}
                    </span>
                    {isBoard && (
                      <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '1px 8px', borderRadius: '10px', background: 'rgba(16,185,129,0.15)', border: '1px solid #10b981', color: '#10b981' }}>
                        🟢 Board Here
                      </span>
                    )}
                    {isAlight && (
                      <span style={{ fontSize: '0.72rem', fontWeight: 700, padding: '1px 8px', borderRadius: '10px', background: 'rgba(239,68,68,0.15)', border: '1px solid #ef4444', color: '#ef4444' }}>
                        🔴 Alight Here
                      </span>
                    )}
                  </div>
                  {(isFirst && !isBoard) && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Route Start</span>
                  )}
                  {(isLast && !isAlight) && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Route End</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}

export default function PredictPage() {
  const { t } = useLanguage();
  const [searchParams] = useSearchParams();
  const [currentStop, setCurrentStop] = useState(searchParams.get("from") || "");
  const [destination, setDestination] = useState(searchParams.get("to") || "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PredictionResponse | null>(null);
  const [expandedMap, setExpandedMap] = useState(false);
  const [showBestRoute, setShowBestRoute] = useState(false);
  const [showLegRoutes, setShowLegRoutes] = useState<Record<number, boolean>>({});
  const [showAllOptions, setShowAllOptions] = useState(false);
  const navigate = useNavigate();
  const { history, addHistory, removeHistory, clearHistory } = useSearchHistory("bmtc_history_predict_routes");
  const { token } = useAuth();
  // What speech recognition actually heard, shown back verbatim so a wrong
  // transcription is visible rather than silently searched.
  const [heard, setHeard] = useState("");
  const [crowding, setCrowding] = useState<{ status: string; crowding_level: string | null; report_count: number } | null>(null);
  const [submittingCrowding, setSubmittingCrowding] = useState(false);

  // Real, commuter-reported crowding for the resolved bus (see
  // crowding_service.py) -- separate from tracking_service.py's simulated
  // per-bus occupancy figure, which is disclosed demo data and must never
  // be presented as if it were this.
  useEffect(() => {
    const busNumber = result?.best_match?.bus_number;
    if (!busNumber) {
      setCrowding(null);
      return;
    }
    apiFetch(`/crowding/route/${encodeURIComponent(busNumber)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => setCrowding(data))
      .catch(() => setCrowding(null));
  }, [result?.best_match?.bus_number]);

  const reportCrowding = async (level: "low" | "medium" | "high" | "full") => {
    const busNumber = result?.best_match?.bus_number;
    if (!busNumber) return;
    if (!token) {
      toast.error("Log in to report crowding");
      return;
    }
    setSubmittingCrowding(true);
    try {
      const response = await apiFetch(`/crowding/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          route_number: busNumber,
          crowding_level: level,
          stop_name: result?.best_match?.matched_current_stop,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not submit report");
      toast.success("Thanks — crowding report submitted");
      apiFetch(`/crowding/route/${encodeURIComponent(busNumber)}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => setCrowding(data))
        .catch(() => { });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not submit report");
    } finally {
      setSubmittingCrowding(false);
    }
  };

  // Takes the stops as arguments rather than reading state, so a caller that
  // has just set them can search immediately -- setState is async, and voice
  // search would otherwise run against the previous pair.
  const runSearch = async (from: string, to: string) => {
    setLoading(true);
    setError("");
    try {
      const fetchedPlan = await api.planRoute(from, to, 50);
      setCurrentStop(fetchedPlan.currentStop);
      setDestination(fetchedPlan.destination);
      setResult(fetchedPlan.result);
      // save this to history so they don't have to type it again
      addHistory(`${fetchedPlan.currentStop} -> ${fetchedPlan.destination}`);
    } catch (err: any) {
      setError(err.message || "Failed to fetch prediction");
    } finally {
      setLoading(false);
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    await runSearch(currentStop, destination);
  };

  // Speech-to-text will not render Bengaluru stop names cleanly -- expect
  // "Yeshawanthapura" and "Kottigepalya" to come back mangled. That is fine:
  // planRoute() already routes everything through /autocomplete and the
  // backend's fuzzy resolver, which exist precisely to absorb this. What the
  // user must never get is a silent reinterpretation, so whatever was heard is
  // shown verbatim next to the result for them to check.
  const handleTranscript = (transcript: string) => {
    setHeard(transcript);
    setError("");
    const parsed = parseRouteQuery(transcript);
    if (!parsed) {
      // One stop only -- fill the origin and let them say or type the rest,
      // rather than guessing at a destination.
      setCurrentStop(transcript);
      setError(`Heard "${transcript}". Say both stops, for example "Silk Board to Marathahalli".`);
      return;
    }
    setCurrentStop(parsed.origin);
    setDestination(parsed.destination);
    void runSearch(parsed.origin, parsed.destination);
  };

  const swap = () => { setCurrentStop(destination); setDestination(currentStop); };

  return (
    <div className="page-container">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="predict-page">
        <div className="page-header bento-card" style={{ padding: '1.25rem 2rem', marginBottom: '2rem', display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          {/* Back button */}
          <button
            type="button"
            onClick={() => { if (result) { setResult(null); setShowBestRoute(false); setShowLegRoutes({}); } else { navigate(-1); } }}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'var(--surface-strong)', border: '1px solid var(--line-strong)',
              borderRadius: '50%', width: '38px', height: '38px', cursor: 'pointer',
              color: 'var(--text)', flexShrink: 0, transition: 'background 0.15s'
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-sunken)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'var(--surface-strong)')}
            title={result ? 'Back to Search' : 'Go Back'}
          >
            <ArrowLeft size={18} />
          </button>

          <Sparkles size={24} className="text-accent" style={{ flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <h1 className="bento-title" style={{ margin: 0 }}>{t("predict.title")}</h1>
            <p className="text-accent" style={{ margin: 0, fontSize: '0.9rem' }}>{t("predict.subtitle")}</p>
          </div>
          {/* Renders nothing at all where the Web Speech API is unavailable
              (notably the Capacitor Android WebView) -- see VoiceButton. */}
          <VoiceButton onTranscript={handleTranscript} onError={setError} />
        </div>

        {/* Search Input Box */}
        <form onSubmit={submit} className="predict-form bento-card" style={{ padding: '2rem', marginBottom: '2rem', overflow: 'visible', position: 'relative', zIndex: 50 }}>
          <div className="predict-inputs">
            <AutocompleteInput label={t("predict.current_stop")} value={currentStop} kind="stop" placeholder="Kempegowda Bus Station" onChange={setCurrentStop} />
            <div style={{ display: 'flex', justifyContent: 'center', margin: '0 10px', alignSelf: 'flex-end', marginBottom: '4px' }}>
              <button type="button" onClick={swap} className="icon-button bento-btn" style={{ padding: '12px', minWidth: 'auto', height: 'auto', borderRadius: '50%', background: 'var(--brand)', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 4px 10px rgba(0, 229, 200, 0.3)' }} title={t("predict.swap")}>
                <ArrowRightLeft size={18} />
              </button>
            </div>
            <AutocompleteInput label={t("predict.destination")} value={destination} kind="stop" placeholder="Marathahalli" onChange={setDestination} />
          </div>
          {heard && (
            <p className="small-copy" style={{ margin: '0.5rem 0 0', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Mic size={13} className="text-accent" />
              <span>Heard: “{heard}” — correct the stops above if that isn’t right.</span>
            </p>
          )}
          {error && <p className="error-text">{error}</p>}
          <button type="submit" className="bento-btn" style={{ width: '100%', display: 'flex', justifyContent: 'center', gap: '8px' }} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" size={18} /> : <Search size={18} />}
            <span>{loading ? t("predict.searching") : t("predict.search")}</span>
          </button>
        </form>

        {/* User's Search History */}
        {!result && history.length > 0 && (
          <div className="bento-card" style={{ padding: '1.5rem', marginBottom: '2rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h3 className="bento-title" style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Clock size={16} className="text-accent" /> {t("predict.recent_searches") || "Recent Searches"}
              </h3>
              <button type="button" onClick={() => clearHistory()} style={{ background: 'none', border: 'none', color: 'var(--brand)', cursor: 'pointer', fontSize: '0.8rem' }}>
                Clear All
              </button>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
              {history.map(item => {
                const [from, to] = item.split(' -> ');
                if (!from || !to) return null;
                return (
                  <div key={item} style={{ display: 'flex', alignItems: 'center', background: 'var(--surface-strong)', padding: '6px 12px', borderRadius: '20px', fontSize: '0.9rem', gap: '8px', border: '1px solid var(--line-strong)' }}>
                    <button type="button" style={{ background: 'none', border: 'none', color: 'var(--text)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }} onClick={() => {
                      setCurrentStop(from);
                      setDestination(to);
                    }}>
                      <span>{from}</span> <ArrowRightLeft size={12} className="text-muted" /> <span>{to}</span>
                    </button>
                    <button type="button" onClick={() => removeHistory(item)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex' }}>
                      <X size={12} />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Default Nearest Metro Finder Widget when no search active */}
        {!result && (
          <div style={{ marginTop: '2rem' }}>
            <NearestMetroPanel
              initialStop={destination || "Marathahalli"}
              title="🚈 Namma Metro Connection Finder"
              showSearch={true}
            />
          </div>
        )}

        {/* Real, moderated service disruption alerts affecting this
            journey (see alerts_service.py) -- only rendered when there
            genuinely are active alerts; an empty array shows nothing,
            never a fabricated "all clear" banner. */}
        {result && result.active_alerts && result.active_alerts.length > 0 && (
          <div style={{ marginBottom: '1rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {result.active_alerts.map((alert) => {
              const severityColor = alert.severity === "severe" ? "#f43f5e" : alert.severity === "moderate" ? "#f59e0b" : "#3b82f6";
              return (
                <div
                  key={alert.id}
                  style={{
                    padding: "0.9rem 1.1rem",
                    borderRadius: "12px",
                    background: `${severityColor}15`,
                    border: `1px solid ${severityColor}60`,
                    display: "flex",
                    gap: "0.6rem",
                    alignItems: "flex-start",
                  }}
                >
                  <span style={{ fontSize: "1.1rem" }}>⚠️</span>
                  <div>
                    <strong style={{ color: severityColor, fontSize: "0.92rem" }}>{alert.title}</strong>
                    <p className="text-muted" style={{ margin: "2px 0 0 0", fontSize: "0.85rem" }}>{alert.description}</p>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Results */}
        <AnimatePresence mode="wait">
          {result && (
            <motion.div key="results" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="predict-results">
              {/* Best Match */}
              {result.best_match && (
                <div className="best-bus-card bento-card" style={{ padding: '2rem', position: 'relative', overflow: 'hidden' }}>
                  <div style={{ position: 'absolute', top: 0, right: 0, width: '200px', height: '200px', background: 'var(--gradient-brand)', opacity: 0.06, borderRadius: '50%', filter: 'blur(40px)', pointerEvents: 'none' }} />

                  <div className="best-bus-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <span className="bus-badge" style={{ fontSize: '1.25rem', padding: '0.5rem 1.1rem' }}>
                        {result.best_match.bus_number}
                      </span>
                      <div>
                        <h2 className="bento-title" style={{ fontSize: '1.3rem', margin: 0 }}>{t("predict.best_bus")}</h2>
                        <span className="text-muted" style={{ fontSize: '0.88rem' }}>{result.best_match.route_name}</span>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <div className="confidence-badge" style={{ background: 'var(--surface-strong)', color: 'var(--text)', border: '1px solid var(--line-strong)', padding: '4px 12px', borderRadius: '20px', fontSize: '0.82rem', fontWeight: 600 }}>
                        {result.best_match.total_stops} stops
                      </div>
                      {result.best_match.distance_km && (
                        <div className="confidence-badge" style={{ background: 'var(--surface-strong)', color: 'var(--brand-strong)', border: '1px solid var(--line-strong)', padding: '4px 12px', borderRadius: '20px', fontSize: '0.82rem', fontWeight: 600 }}>
                          {result.best_match.distance_km} km
                        </div>
                      )}
                      <div className="confidence-badge" style={{ background: 'var(--gradient-brand-subtle)', border: '1px solid var(--brand)', color: 'var(--brand-strong)', padding: '4px 12px', borderRadius: '20px', fontSize: '0.82rem', fontWeight: 700 }}>
                        {((result.best_match.confidence ?? result.best_match.relevance_score ?? 0) <= 1 ? (result.best_match.confidence ?? result.best_match.relevance_score ?? 0) * 100 : (result.best_match.confidence ?? result.best_match.relevance_score ?? 0)).toFixed(1)}% {t("predict.confidence")}
                      </div>
                    </div>
                  </div>

                  {/* Bus transfer indicator -- the badge above only shows
                      the FIRST bus to board (see predictor.py's comment on
                      why), so a transfer journey needs an equally visible
                      signal that a second bus is required, not just the
                      smaller message text further down the page. */}
                  {(result.best_match.transfers ?? 0) > 0 && (
                    <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 14px', borderRadius: '20px', background: 'rgba(245, 158, 11, 0.15)', border: '1px solid #f59e0b', color: '#f59e0b', fontSize: '0.82rem', fontWeight: 700 }}>
                        🔄 {result.best_match.transfers} Transfer{(result.best_match.transfers ?? 0) > 1 ? "s" : ""} Required — {result.best_match.bus_chain}
                      </div>
                    </div>
                  )}

                  {/* Metro interchange badge -- only shown when the route
                      genuinely passes a known interchange (real backend
                      signal, see predictor.py's metro_interchange field).
                      Previously this was rendered unconditionally on every
                      single result regardless of whether any metro
                      connection actually existed for that route. */}
                  {result.best_match.metro_interchange && (
                    <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '6px 14px', borderRadius: '20px', background: 'rgba(124, 58, 237, 0.15)', border: '1px solid var(--brand-2)', color: 'var(--brand-2)', fontSize: '0.82rem', fontWeight: 700 }}>
                        🚇 Connects to Namma Metro at {result.best_match.metro_interchange.station_name}
                        {result.best_match.metro_interchange.lines?.length ? ` (${result.best_match.metro_interchange.lines.join(", ")})` : ""}
                      </div>
                    </div>
                  )}

                  {/* Real, commuter-reported crowding (see
                      crowding_service.py) -- distinct from the simulated
                      per-bus occupancy figure in Live Tracking, which is
                      disclosed demo data. Shows an honest "not enough
                      reports yet" state rather than a fabricated number
                      when real report volume is too low. */}
                  <div style={{ marginTop: '1.25rem', padding: '1rem 1.1rem', background: 'var(--surface-strong)', borderRadius: '14px', border: '1px solid var(--line-strong)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '0.6rem' }}>
                      <Users size={16} className="text-accent" />
                      <strong style={{ fontSize: '0.88rem' }}>How crowded is {result.best_match.bus_number}?</strong>
                    </div>
                    {crowding?.status === "ok" ? (
                      <p className="text-muted" style={{ fontSize: '0.82rem', margin: '0 0 0.75rem 0' }}>
                        Commuters report <strong>{crowding.crowding_level}</strong> crowding right now
                        ({crowding.report_count} report{crowding.report_count === 1 ? "" : "s"} in the last 45 min).
                      </p>
                    ) : (
                      <p className="text-muted" style={{ fontSize: '0.82rem', margin: '0 0 0.75rem 0' }}>
                        Not enough recent reports yet — be the first to share.
                      </p>
                    )}
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                      {(["low", "medium", "high", "full"] as const).map((level) => (
                        <button
                          key={level}
                          type="button"
                          disabled={submittingCrowding}
                          onClick={() => reportCrowding(level)}
                          className="bento-btn secondary"
                          style={{ padding: '5px 12px', fontSize: '0.78rem', textTransform: 'capitalize' }}
                        >
                          {level}
                        </button>
                      ))}
                    </div>
                  </div>

                  <SafetyPanel
                    currentStop={currentStop}
                    destination={destination}
                    busNumber={result.best_match.bus_number}
                    matchedCurrentStop={result.best_match.matched_current_stop}
                    matchedDestination={result.best_match.matched_destination}
                  />

                  {/* Route Stop Timeline — compact summary */}
                  <div style={{ marginTop: '1.5rem', padding: '1.25rem', background: 'var(--surface-strong)', borderRadius: '14px', border: '1px solid var(--line-strong)' }}>
                    <div className="route-timeline" style={{ margin: 0 }}>
                      <div className="timeline-step">
                        <div className="timeline-node board" />
                        <div className="timeline-content">
                          <span className="timeline-stop-name">{result.best_match.matched_current_stop || currentStop}</span>
                          <span className="timeline-tag" style={{ color: '#10b981', fontWeight: 600 }}>Boarding Stop</span>
                        </div>
                      </div>
                      <div className="timeline-step">
                        <div className="timeline-node alight" />
                        <div className="timeline-content">
                          <span className="timeline-stop-name">{result.best_match.matched_destination || destination}</span>
                          <span className="timeline-tag" style={{ color: '#ef4444', fontWeight: 600 }}>Alighting Destination</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 🚈 First-mile: nearest metro to the boarding stop.
                      Previously only the destination end had this panel --
                      a commuter deciding whether to walk to a nearby metro
                      station instead of (or in addition to) the bus needs
                      this at the START of the trip too, not just the end. */}
                  <div style={{ marginTop: '1.25rem' }}>
                    <NearestMetroPanel
                      initialStop={result.best_match.matched_current_stop || currentStop}
                      title={`🚈 Nearest Metro to Boarding Stop: ${result.best_match.matched_current_stop || currentStop}`}
                      showSearch={false}
                    />
                  </div>

                  {/* 🚈 Metro Connection & Map displayed directly under Destination Stop */}
                  <div style={{ marginTop: '1.25rem' }}>
                    <NearestMetroPanel
                      initialStop={result.best_match.matched_destination || destination}
                      title={`🚈 Nearest Metro to Destination: ${result.best_match.matched_destination || destination}`}
                      showSearch={false}
                    />
                  </div>

                  {/* Inline full route stops panel */}
                  <AnimatePresence>
                    {showBestRoute && (
                      <RouteStopsPanel
                        routePath={result.best_match.route_path || []}
                        fromStop={result.best_match.matched_current_stop || currentStop}
                        toStop={result.best_match.matched_destination || destination}
                        busNumber={result.best_match.bus_number}
                      />
                    )}
                  </AnimatePresence>

                  <div className="best-bus-actions" style={{ marginTop: '1.5rem', display: 'flex', justifyContent: 'flex-end', gap: '10px', flexWrap: 'wrap' }}>
                    <button
                      className="bento-btn secondary"
                      onClick={() => setShowBestRoute(v => !v)}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '0.6rem 1.4rem', fontSize: '0.9rem', borderRadius: '12px' }}
                    >
                      <Info size={15} />
                      {showBestRoute ? 'Hide Route Stops' : 'View Route Stops'}
                    </button>
                    <Link to={`/track?bus=${result.best_match.bus_number}`} className="bento-btn" style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '0.6rem 1.5rem', fontSize: '0.95rem', borderRadius: '12px', background: 'var(--gradient-brand)', color: 'white', boxShadow: 'var(--shadow-brand)' }}>
                      <Navigation size={16} /> Live Track
                    </Link>
                  </div>
                </div>
              )}



              {/* Alternative Route Steps */}
              {result.alternatives && result.alternatives.length > (result.best_match ? 1 : 0) && (
                <div style={{ marginTop: '2rem' }}>
                  {!result.best_match && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                      <h2 className="bento-title" style={{ fontSize: '1.4rem', margin: 0 }}>Recommended Route</h2>
                      <span className="confidence-badge" style={{ background: 'var(--surface-strong)', color: 'var(--text)', border: '1px solid var(--line-strong)', padding: '4px 12px', borderRadius: '20px' }}>
                        {result.alternatives[0].total_stops} stops
                      </span>
                    </div>
                  )}

                  {/* If best_match exists, alternatives[0] is the best_match itself, so we skip index 0. If not, alternatives[0] is the recommended route. */}
                  {!result.best_match && result.alternatives[0].legs.map((leg: any, stepIndex: number) => (
                    <div key={stepIndex} className="bento-card" style={{ padding: '1.5rem', marginBottom: '1.25rem', borderRadius: '16px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span className="step-badge" style={{ background: 'var(--gradient-brand)', color: 'white', width: '28px', height: '28px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.85rem', fontWeight: 'bold' }}>
                            {stepIndex + 1}
                          </span>
                          <span className="bus-badge" style={{ fontSize: '1.05rem', padding: '0.35rem 0.85rem' }}>
                            {leg.bus_number}
                          </span>
                        </div>
                        <span style={{ fontSize: '0.82rem', color: 'var(--text-3)' }}>{leg.stop_count} stops</span>
                      </div>

                      <div className="route-timeline" style={{ margin: '1rem 0' }}>
                        <div className="timeline-step">
                          <div className="timeline-node board" />
                          <div className="timeline-content">
                            <span className="timeline-stop-name">{leg.from_stop}</span>
                            <span className="timeline-tag" style={{ color: '#10b981', fontWeight: 600 }}>Board {leg.bus_number}</span>
                          </div>
                        </div>
                        <div className="timeline-step">
                          <div className="timeline-node alight" />
                          <div className="timeline-content">
                            <span className="timeline-stop-name">{leg.to_stop}</span>
                            <span className="timeline-tag" style={{ color: '#ef4444', fontWeight: 600 }}>Alight</span>
                          </div>
                        </div>
                      </div>

                      <AnimatePresence>
                        {showLegRoutes[stepIndex] && (
                          <RouteStopsPanel
                            routePath={leg.route_path || []}
                            fromStop={leg.from_stop}
                            toStop={leg.to_stop}
                            busNumber={leg.bus_number}
                          />
                        )}
                      </AnimatePresence>

                      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem', gap: '8px' }}>
                        <button
                          className="bento-btn secondary"
                          onClick={() => setShowLegRoutes(prev => ({ ...prev, [stepIndex]: !prev[stepIndex] }))}
                          style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '0.45rem 1.1rem', fontSize: '0.85rem', borderRadius: '10px' }}
                        >
                          <Info size={13} />
                          {showLegRoutes[stepIndex] ? 'Hide Stops' : 'View Route'}
                        </button>
                        <Link to={`/track?bus=${leg.bus_number}`} className="bento-btn secondary" style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '0.45rem 1.1rem', fontSize: '0.85rem', borderRadius: '10px' }}>
                          <Navigation size={14} /> Live Track
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Other options section — Displays ALL predicted direct and connecting buses */}
              {result.alternatives && result.alternatives.length > 1 && (
                <div className="bento-card" style={{ padding: '2rem', marginTop: '2rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '10px' }}>
                    <div>
                      <h3 className="bento-title" style={{ fontSize: '1.25rem', margin: 0 }}>
                        Other Direct & Connecting Bus Options
                      </h3>
                      <span className="text-muted" style={{ fontSize: '0.88rem' }}>
                        Found {result.alternatives.length - 1} additional bus route{result.alternatives.length - 1 > 1 ? 's' : ''} connecting these stops
                      </span>
                    </div>

                    {result.alternatives.length - 1 > 4 && (
                      <button
                        type="button"
                        className="bento-btn secondary"
                        onClick={() => setShowAllOptions(prev => !prev)}
                        style={{ padding: '0.45rem 1.1rem', fontSize: '0.85rem', borderRadius: '10px', display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                      >
                        {showAllOptions ? 'Show Top 4 Options' : `View All ${result.alternatives.length - 1} Bus Routes`}
                      </button>
                    )}
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {(showAllOptions ? result.alternatives.slice(1) : result.alternatives.slice(1, 5)).map((alt: any, idx: number) => {
                      const firstLeg = alt.legs?.[0];
                      const busNum = firstLeg?.bus_number || alt.bus_chain || `Option ${idx + 2}`;
                      const isDirect = alt.transfers === 0;

                      return (
                        <div
                          key={idx}
                          style={{
                            padding: '1.2rem',
                            background: 'var(--surface-strong)',
                            borderRadius: '12px',
                            border: '1px solid var(--line-strong)',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.6rem'
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                              <span
                                className="bus-badge"
                                style={{
                                  fontSize: '0.95rem',
                                  padding: '0.35rem 0.85rem',
                                  borderRadius: '8px',
                                  fontWeight: 700
                                }}
                              >
                                {busNum}
                              </span>
                              <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                                Option {idx + 2}
                              </span>
                              <span
                                style={{
                                  fontSize: '0.75rem',
                                  padding: '2px 8px',
                                  borderRadius: '12px',
                                  fontWeight: 600,
                                  background: isDirect ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                                  color: isDirect ? '#10b981' : '#f59e0b',
                                  border: `1px solid ${isDirect ? '#10b981' : '#f59e0b'}`
                                }}
                              >
                                {isDirect ? 'Direct Route' : `${alt.transfers} Transfer`}
                              </span>
                            </div>

                            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                              <span style={{ color: 'var(--brand)', fontWeight: 600, fontSize: '0.88rem' }}>
                                {alt.total_stops} stops
                              </span>
                              {busNum && (
                                <Link
                                  to={`/track?bus=${encodeURIComponent(busNum)}`}
                                  className="bento-btn secondary"
                                  style={{
                                    textDecoration: 'none',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '6px',
                                    padding: '0.35rem 0.85rem',
                                    fontSize: '0.82rem',
                                    borderRadius: '8px'
                                  }}
                                >
                                  <Navigation size={13} /> Track Bus
                                </Link>
                              )}
                            </div>
                          </div>

                          <div className="text-muted" style={{ fontSize: '0.9rem', lineHeight: '1.5' }}>
                            {alt.summary}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {!showAllOptions && result.alternatives.length - 1 > 4 && (
                    <div style={{ textAlign: 'center', marginTop: '1.25rem' }}>
                      <button
                        type="button"
                        className="bento-btn secondary"
                        onClick={() => setShowAllOptions(true)}
                        style={{ padding: '0.6rem 1.8rem', fontSize: '0.9rem', borderRadius: '12px' }}
                      >
                        + Show {result.alternatives.length - 1 - 4} More Bus Routes (502-H, 248-B, 248-BA, 248-N, etc.)
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* No results */}
              {!result.best_match && (!result.alternatives || result.alternatives.length === 0) && (
                <div className="bento-card empty-state" style={{ marginTop: '2rem' }}>
                  <p>{t("predict.no_result")}</p>
                  <p className="text-muted">{result.message}</p>
                </div>
              )}

              {/* Route Map Feature */}
              {result.best_match && result.best_match.route_coordinates && result.best_match.route_coordinates.filter((c: any) => c.lat && c.lon).length > 0 && (
                <div className="bento-card" style={{ padding: '2rem', marginTop: '2rem' }}>
                  <h3 className="bento-title" style={{ fontSize: '1.2rem', marginBottom: '1rem' }}>Route Map</h3>
                  {/* One map implementation, shared. This page used to inline
                      its own copy alongside components/RouteMap.tsx, and the
                      two drifted -- the inline one drew a single line through
                      every leg of a transfer journey as though it were one
                      bus.

                      The full-screen backdrop lives inside RouteMap now,
                      because it has to be portaled to document.body: rendered
                      here it sat inside .bento-card, whose backdrop-filter
                      makes it the containing block for fixed positioning, so
                      "cover the viewport" only ever covered the card. */}
                  <RouteMap
                    coordinates={result.best_match.route_coordinates as any}
                    legs={(result.best_match as any).legs}
                    routePath={result.best_match.route_path}
                    expanded={expandedMap}
                    onToggleExpand={() => setExpandedMap(!expandedMap)}
                  />
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}