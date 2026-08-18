import { FormEvent, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, Mic, Vote, CheckCircle, AlertTriangle, Map, ArrowUpDown, ArrowLeft, Bus, Clock, TrainFront, Users } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { useLanguage } from "../contexts/LanguageContext";
import { AutocompleteInput } from "../components/AutocompleteInput";
import { VoiceButton } from "../components/VoiceButton";
import { parseRouteQuery } from "../utils/parseRouteQuery";
import { timeLabel } from "../utils/format";
import toast from "react-hot-toast";
import { apiFetch } from "../lib/apiClient";

/** What GET /votes/allocation returns for one origin-destination pair. */
interface Allocation {
  query: { current_stop: string; destination: string };
  allocated_bus: any | null;
  other_options: any[];
  demand: any;
  depot_review: any | null;
  source: string;
  message: string | null;
}

export default function VotePage() {
  const { token } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [currentStop, setCurrentStop] = useState("");
  const [destination, setDestination] = useState("");
  // timePref is the enum value sent to the backend: any|morning_peak|afternoon|evening_peak|night
  const [timePref, setTimePref] = useState("morning_peak");
  // displayTime is only used for the clock UI label
  const [hour, setHour] = useState("08");
  const [minute, setMinute] = useState("30");
  const [ampm, setAmpm] = useState<"AM" | "PM">("AM");
  const [loading, setLoading] = useState(false);
  const [personalVotes, setPersonalVotes] = useState<any[]>([]);
  const [communityDemand, setCommunityDemand] = useState<any[]>([]);
  // The bus that actually serves the pair of stops. Loaded on demand and
  // again right after a vote, so the commuter sees what their vote was for.
  const [allocation, setAllocation] = useState<Allocation | null>(null);
  const [allocationLoading, setAllocationLoading] = useState(false);
  const [allocationError, setAllocationError] = useState("");
  // What speech recognition heard, shown verbatim so a mistranscription is
  // visible before the commuter commits a vote to it.
  const [heard, setHeard] = useState("");

  const timeOptions = [
    { value: "any", label: t("vote.time_any") },
    { value: "morning_peak", label: t("vote.time_morning") },
    { value: "afternoon", label: t("vote.time_afternoon") },
    { value: "evening_peak", label: t("vote.time_evening") },
    { value: "night", label: t("vote.time_night") },
  ];

  const loadData = () => {
    if (!token) return;
    
    // grab my recent votes so I can see what I already submitted
    apiFetch(`/votes/my?limit=10`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((data) => setPersonalVotes(data.votes || []))
      .catch(() => {});

    // pull the big community aggregation to show what's hot right now
    apiFetch(`/votes/aggregate?days=7`)
      .then((r) => r.json())
      .then((data) => setCommunityDemand((data.demand || []).slice(0, 8)))
      .catch(() => {});
  };

  useEffect(loadData, [token]);

  /** Ask which bus is allocated to a stop pair. Stops are passed in rather
   *  than read from state because the form clears itself after a vote. */
  const loadAllocation = async (from: string, to: string) => {
    if (!token || !from.trim() || !to.trim()) return;
    setAllocationLoading(true);
    setAllocationError("");
    try {
      const query = `current_stop=${encodeURIComponent(from.trim())}&destination=${encodeURIComponent(to.trim())}`;
      const response = await apiFetch(`/votes/allocation?${query}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();
      if (!response.ok) {
        // 422 carries the engine's own explanation ("Could not find any stop
        // matching ...", "You are already at your destination!") — show that
        // rather than a generic failure the commuter can't act on.
        throw new Error(typeof data.detail === "string" ? data.detail : "Could not look up the allocated bus.");
      }
      setAllocation(data);
    } catch (err: any) {
      setAllocation(null);
      setAllocationError(err?.message || "Could not look up the allocated bus.");
    } finally {
      setAllocationLoading(false);
    }
  };

  /** Fill the stop fields from a spoken phrase like "Silk Board to Marathahalli".
   *
   *  Deliberately does NOT cast the vote. Find-bus can run its search straight
   *  off a transcript because a search is a read and a wrong one costs nothing
   *  but a retry; a vote is a write that feeds depot dispatch recommendations,
   *  and speech recognition mangles Bengaluru stop names often enough that
   *  auto-submitting would put words in the commuter's mouth. So this fills the
   *  form, looks up the allocated bus (also a read) as immediate feedback, and
   *  leaves the actual vote to a deliberate press.
   */
  const handleTranscript = (transcript: string) => {
    setHeard(transcript);
    const parsed = parseRouteQuery(transcript);
    if (!parsed) {
      setCurrentStop(transcript);
      toast(`Heard "${transcript}". Say both stops, e.g. "Silk Board to Marathahalli".`, { icon: "🎤" });
      return;
    }
    setCurrentStop(parsed.origin);
    setDestination(parsed.destination);
    void loadAllocation(parsed.origin, parsed.destination);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!currentStop.trim() || !destination.trim()) {
      toast.error("Please select both stops");
      return;
    }
    setLoading(true);
    // Kept because the form clears below, and the allocation shown afterwards
    // must be for the pair that was actually voted for.
    const votedFrom = currentStop;
    const votedTo = destination;
    try {
      const response = await apiFetch(`/votes`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ current_stop: currentStop, destination, time_preference: timePref }),
      });
      const parsedData = await response.json();

      if (!response.ok) throw new Error(parsedData.detail || "Vote failed");

      if (parsedData.is_flagged) {
        toast(t("vote.flagged"), { icon: "⚠️" });
      } else {
        toast.success(t("vote.success"));
      }
      setCurrentStop("");
      setDestination("");
      loadData();
      // Deliberately not awaited: the vote is already recorded, and a slow or
      // failed lookup here must not make a successful vote look unsuccessful.
      loadAllocation(votedFrom, votedTo);
    } catch (err: any) {
      const msg = typeof err?.message === 'string' ? err.message
        : typeof err === 'string' ? err
        : "Vote submission failed. Please try again.";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="vote-page">
        <div className="page-header bento-card" style={{ padding: '1.25rem 2rem', marginBottom: '2rem', display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
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
          <Vote size={24} className="text-accent" style={{ flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <h1 className="bento-title" style={{ margin: 0 }}>{t("vote.title")}</h1>
            <p className="text-accent" style={{ margin: 0, fontSize: '0.9rem' }}>{t("vote.subtitle")}</p>
          </div>
          {/* Fills the stops only -- see handleTranscript for why a vote is
              never cast from a transcript. Renders nothing where the Web
              Speech API is unavailable. */}
          <VoiceButton onTranscript={handleTranscript} onError={(m) => toast.error(m)} />
        </div>

        <div className="vote-layout">
          {/* Left column: the form, with the allocated bus appearing directly
              under it. One grid child, so the sidebar stays in its own column. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem', minWidth: 0 }}>
          {/* Vote Form */}
          <form onSubmit={handleSubmit} className="vote-form bento-card" style={{ padding: '2rem', overflow: 'visible', position: 'relative', zIndex: 50 }}>
            <div className="form-group">
              <label>{t("vote.current_stop")}</label>
              <AutocompleteInput
                label=""
                value={currentStop}
                kind="stop"
                placeholder="e.g. Silk Board"
                onChange={setCurrentStop}
              />
            </div>

            <div style={{ display: 'flex', justifyContent: 'center', margin: '0' }}>
              <button type="button" onClick={() => { const t = currentStop; setCurrentStop(destination); setDestination(t); }} className="icon-button bento-btn" style={{ padding: '8px', minWidth: 'auto', height: 'auto', borderRadius: '50%' }} title="Swap">
                <ArrowUpDown size={18} />
              </button>
            </div>

            <div className="form-group">
              <label>{t("vote.destination")}</label>
              <AutocompleteInput
                label=""
                value={destination}
                kind="stop"
                placeholder="e.g. Marathahalli"
                onChange={setDestination}
              />
            </div>

            {heard && (
              <p className="text-muted" style={{ fontSize: '0.82rem', margin: '0 0 1rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Mic size={13} className="text-accent" />
                <span>Heard: “{heard}” — check the stops above before voting.</span>
              </p>
            )}

            {/* Alarm-Style Interactive Travel Time Picker */}
            <div className="form-group" style={{ marginBottom: '2rem' }}>
              <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                <span>{t("vote.time_pref")}</span>
                <span style={{ fontSize: '0.8rem', color: 'var(--brand)', fontWeight: 700, padding: '2px 10px', background: 'rgba(0, 229, 200, 0.15)', borderRadius: '12px', border: '1px solid var(--brand)' }}>
                  ⏰ Selected: {hour}:{minute} {ampm}
                </span>
              </label>

              {/* Peak Hour Presets */}
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                <button
                  type="button"
                  className={`bento-btn secondary${timePref === 'morning_peak' ? ' active' : ''}`}
                  style={{ fontSize: '0.78rem', padding: '4px 10px', opacity: timePref === 'morning_peak' ? 1 : 0.7 }}
                  onClick={() => { setHour("08"); setMinute("30"); setAmpm("AM"); setTimePref("morning_peak"); }}
                >
                  🌅 Morning Peak (8:30 AM)
                </button>
                <button
                  type="button"
                  className={`bento-btn secondary${timePref === 'afternoon' ? ' active' : ''}`}
                  style={{ fontSize: '0.78rem', padding: '4px 10px', opacity: timePref === 'afternoon' ? 1 : 0.7 }}
                  onClick={() => { setHour("01"); setMinute("30"); setAmpm("PM"); setTimePref("afternoon"); }}
                >
                  ☀️ Afternoon (1:30 PM)
                </button>
                <button
                  type="button"
                  className={`bento-btn secondary${timePref === 'evening_peak' ? ' active' : ''}`}
                  style={{ fontSize: '0.78rem', padding: '4px 10px', opacity: timePref === 'evening_peak' ? 1 : 0.7 }}
                  onClick={() => { setHour("06"); setMinute("15"); setAmpm("PM"); setTimePref("evening_peak"); }}
                >
                  🌆 Evening Peak (6:15 PM)
                </button>
                <button
                  type="button"
                  className={`bento-btn secondary${timePref === 'night' ? ' active' : ''}`}
                  style={{ fontSize: '0.78rem', padding: '4px 10px', opacity: timePref === 'night' ? 1 : 0.7 }}
                  onClick={() => { setHour("09"); setMinute("45"); setAmpm("PM"); setTimePref("night"); }}
                >
                  🌙 Night (9:45 PM)
                </button>
              </div>

              {/* Alarm Wheel Box */}
              <div style={{ background: 'var(--surface-strong)', padding: '1.25rem', borderRadius: '16px', border: '1px solid var(--line-strong)' }}>
                
                {/* Hours Selector Wheel */}
                <div style={{ marginBottom: '1rem' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-3)', fontWeight: 600, textTransform: 'uppercase', display: 'block', marginBottom: '0.4rem' }}>
                    Select Hour
                  </span>
                  <div style={{ display: 'flex', gap: '0.4rem', overflowX: 'auto', paddingBottom: '0.4rem' }} className="no-scrollbar">
                    {["01","02","03","04","05","06","07","08","09","10","11","12"].map((h) => (
                      <button
                        key={h}
                        type="button"
                        onClick={() => {
                          setHour(h);
                          const h12 = parseInt(h, 10);
                          const h24 = ampm === "PM" ? (h12 === 12 ? 12 : h12 + 12) : (h12 === 12 ? 0 : h12);
                          if (h24 >= 6 && h24 < 11) setTimePref("morning_peak");
                          else if (h24 >= 11 && h24 < 16) setTimePref("afternoon");
                          else if (h24 >= 16 && h24 < 21) setTimePref("evening_peak");
                          else setTimePref("night");
                        }}
                        style={{
                          minWidth: '40px',
                          height: '40px',
                          borderRadius: '10px',
                          fontSize: '0.9rem',
                          fontWeight: 700,
                          cursor: 'pointer',
                          background: hour === h ? 'var(--gradient-brand)' : 'var(--surface-glass)',
                          color: hour === h ? '#ffffff' : 'var(--text)',
                          border: `1px solid ${hour === h ? 'transparent' : 'var(--line-strong)'}`,
                          boxShadow: hour === h ? 'var(--shadow-brand)' : 'none',
                          flexShrink: 0
                        }}
                      >
                        {h}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Minutes Selector Wheel & AM/PM */}
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
                  <div style={{ flex: 1, minWidth: '180px' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-3)', fontWeight: 600, textTransform: 'uppercase', display: 'block', marginBottom: '0.4rem' }}>
                      Select Minute
                    </span>
                    <div style={{ display: 'flex', gap: '0.4rem', overflowX: 'auto', paddingBottom: '0.4rem' }} className="no-scrollbar">
                      {["00","05","10","15","20","25","30","35","40","45","50","55"].map((m) => (
                        <button
                          key={m}
                          type="button"
                          onClick={() => { setMinute(m); /* timePref stays as current peak enum */ }}
                          style={{
                            minWidth: '40px',
                            height: '36px',
                            borderRadius: '8px',
                            fontSize: '0.85rem',
                            fontWeight: 700,
                            cursor: 'pointer',
                            background: minute === m ? 'var(--brand-2)' : 'var(--surface-glass)',
                            color: minute === m ? '#ffffff' : 'var(--text)',
                            border: `1px solid ${minute === m ? 'transparent' : 'var(--line-strong)'}`,
                            flexShrink: 0
                          }}
                        >
                          {m}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* AM/PM Switcher */}
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-3)', fontWeight: 600, textTransform: 'uppercase', display: 'block', marginBottom: '0.4rem' }}>
                      Meridiem
                    </span>
                    <div style={{ display: 'flex', gap: '0.3rem', background: 'var(--surface-glass)', padding: '4px', borderRadius: '10px', border: '1px solid var(--line-strong)' }}>
                      <button
                        type="button"
                        onClick={() => {
                          setAmpm("AM");
                          const h12 = parseInt(hour, 10);
                          const h24 = h12 === 12 ? 0 : h12;
                          if (h24 >= 6 && h24 < 11) setTimePref("morning_peak");
                          else if (h24 >= 11 && h24 < 16) setTimePref("afternoon");
                          else if (h24 >= 16 && h24 < 21) setTimePref("evening_peak");
                          else setTimePref("night");
                        }}
                        style={{
                          padding: '6px 14px',
                          borderRadius: '8px',
                          fontSize: '0.82rem',
                          fontWeight: 700,
                          cursor: 'pointer',
                          background: ampm === "AM" ? 'var(--gradient-brand)' : 'transparent',
                          color: ampm === "AM" ? '#fff' : 'var(--text-3)',
                          border: 'none'
                        }}
                      >
                        AM
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setAmpm("PM");
                          const h12 = parseInt(hour, 10);
                          const h24 = h12 === 12 ? 12 : h12 + 12;
                          if (h24 >= 6 && h24 < 11) setTimePref("morning_peak");
                          else if (h24 >= 11 && h24 < 16) setTimePref("afternoon");
                          else if (h24 >= 16 && h24 < 21) setTimePref("evening_peak");
                          else setTimePref("night");
                        }}
                        style={{
                          padding: '6px 14px',
                          borderRadius: '8px',
                          fontSize: '0.82rem',
                          fontWeight: 700,
                          cursor: 'pointer',
                          background: ampm === "PM" ? 'var(--gradient-brand)' : 'transparent',
                          color: ampm === "PM" ? '#fff' : 'var(--text-3)',
                          border: 'none'
                        }}
                      >
                        PM
                      </button>
                    </div>
                  </div>

                </div>
              </div>
            </div>

            {/* Generously Spaced Submit Vote Button */}
            <div style={{ marginTop: '2rem', paddingTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              <button type="submit" className="bento-btn" style={{ width: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', padding: '0.85rem', fontSize: '1.05rem', background: 'var(--gradient-brand)', color: 'white', border: 'none', borderRadius: '14px', boxShadow: 'var(--shadow-brand)' }} disabled={loading}>
                {loading ? <Loader2 className="animate-spin" size={20} /> : <Vote size={20} />}
                <span>{loading ? t("vote.submitting") : t("vote.submit")}</span>
              </button>
              {/* Available before voting too — knowing a bus already runs the
                  pair is exactly the context that makes a vote meaningful. */}
              <button
                type="button"
                className="bento-btn secondary"
                style={{ width: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', padding: '0.6rem', fontSize: '0.9rem', borderRadius: '12px' }}
                disabled={allocationLoading || !currentStop.trim() || !destination.trim()}
                onClick={() => loadAllocation(currentStop, destination)}
              >
                {allocationLoading ? <Loader2 className="animate-spin" size={16} /> : <Bus size={16} />}
                <span>{allocationLoading ? t("vote.allocation_loading") : t("vote.allocation_check")}</span>
              </button>
            </div>
          </form>

          <AllocatedBusPanel
            allocation={allocation}
            loading={allocationLoading}
            error={allocationError}
            t={t}
          />
          </div>

          {/* Sidebar */}
          <div className="vote-sidebar">
            {/* Community Demand Overview */}
            <div className="aggregate-panel bento-card" style={{ padding: '2rem', marginBottom: '2rem' }}>
              <h2 className="bento-title" style={{ fontSize: '1.2rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <ArrowUpDown size={20} className="text-accent" />
                {t("vote.community_demand")}
              </h2>
              {communityDemand.length === 0 ? (
                <p className="text-muted">{t("common.no_data")}</p>
              ) : (
                <div className="aggregate-list">
                  {communityDemand.map((agg: any, i: number) => (
                    <div key={i} className="trending-item">
                      <div className="trending-route">
                        {agg.current_stop} → {agg.destination}
                      </div>
                      <div className="trending-votes">
                        <span className="vote-count-badge">{agg.vote_count}</span> {t("common.votes")}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* My personal vote history */}
            <div className="bento-card" style={{ padding: '2rem' }}>
              <h3 className="bento-title" style={{ fontSize: '1.2rem' }}>{t("vote.my_votes")}</h3>
              {personalVotes.length === 0 ? (
                <p className="text-muted">No votes yet</p>
              ) : (
                <div className="trending-list">
                  {personalVotes.slice(0, 5).map((v: any) => (
                    <div key={v.id} className="trending-item">
                      <div className="trending-route">{v.current_stop} → {v.destination}</div>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '8px', flexWrap: 'wrap' }}>
                        <span className="vote-time-badge">{v.time_preference}</span>
                        <Link to={`/predict?from=${encodeURIComponent(v.current_stop)}&to=${encodeURIComponent(v.destination)}`} className="bento-btn" style={{ padding: '4px 12px', fontSize: '0.8rem', height: 'auto', textDecoration: 'none' }}>
                          <Map size={12} style={{ marginRight: '4px' }} /> View Route
                        </Link>
                        <button
                          type="button"
                          className="bento-btn secondary"
                          style={{ padding: '4px 12px', fontSize: '0.8rem', height: 'auto' }}
                          disabled={allocationLoading}
                          onClick={() => loadAllocation(v.current_stop, v.destination)}
                          title={t("vote.allocation_check")}
                        >
                          <Bus size={12} style={{ marginRight: '4px' }} /> {t("vote.allocation_title")}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

/** The bus BMTC's published timetable already runs between the two stops the
 *  commuter picked, plus what the votes for that pair add up to.
 *
 *  Every figure here comes from GET /votes/allocation, which in turn comes
 *  from the prediction engine and the vote collection. Nothing on this panel
 *  is invented locally, and the two halves fail independently: when the
 *  database is down the bus still shows and the vote counts say why they
 *  cannot. */
function AllocatedBusPanel({
  allocation,
  loading,
  error,
  t,
}: {
  allocation: Allocation | null;
  loading: boolean;
  error: string;
  t: (key: string) => string;
}) {
  if (error) {
    return (
      <div className="bento-card" style={{ padding: '1.5rem', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
        <AlertTriangle size={20} style={{ color: '#f59e0b', flexShrink: 0, marginTop: '2px' }} />
        <div>
          <h3 className="bento-title" style={{ fontSize: '1.05rem', margin: 0 }}>{t("vote.allocation_title")}</h3>
          <p className="text-muted" style={{ margin: '4px 0 0 0', fontSize: '0.88rem' }}>{error}</p>
        </div>
      </div>
    );
  }

  if (loading && !allocation) {
    return (
      <div className="bento-card" style={{ padding: '1.5rem', display: 'flex', gap: '12px', alignItems: 'center' }}>
        <Loader2 className="animate-spin" size={20} />
        <span className="text-muted" style={{ fontSize: '0.9rem' }}>{t("vote.allocation_loading")}</span>
      </div>
    );
  }

  if (!allocation) return null;

  const bus = allocation.allocated_bus;
  const demand = allocation.demand || {};
  const review = allocation.depot_review;

  const transferLabel = !bus
    ? ""
    : bus.transfers === 0
      ? t("vote.allocation_direct")
      : bus.transfers === 1
        ? t("vote.allocation_transfer")
        : `${bus.transfers} ${t("vote.allocation_transfers")}`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bento-card"
      style={{ padding: '1.75rem', opacity: loading ? 0.6 : 1, transition: 'opacity 0.15s' }}
    >
      <h3 className="bento-title" style={{ fontSize: '1.15rem', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Bus size={20} className="text-accent" />
        {t("vote.allocation_title")}
      </h3>
      <p className="text-muted" style={{ margin: '4px 0 1.25rem 0', fontSize: '0.9rem', fontWeight: 600 }}>
        {allocation.query.current_stop} → {allocation.query.destination}
      </p>

      {!bus ? (
        <p className="text-muted" style={{ margin: 0, fontSize: '0.9rem', lineHeight: 1.5 }}>
          {t("vote.allocation_none")}
        </p>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap', marginBottom: '1rem' }}>
            <span className="bus-badge" style={{ fontSize: '1.05rem', padding: '0.4rem 0.9rem' }}>{bus.bus_chain}</span>
            <span style={{ padding: '3px 10px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 800, background: 'var(--surface-strong)', border: '1px solid var(--line-strong)', color: 'var(--text-3)' }}>
              {transferLabel}
            </span>
            {bus.metro_interchange?.has_metro_connection && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', padding: '3px 10px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 700, background: 'rgba(167, 139, 250, 0.15)', border: '1px solid #a78bfa50', color: '#a78bfa' }}>
                <TrainFront size={12} /> {bus.metro_interchange.station_name}
              </span>
            )}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
            <div style={{ padding: '0.75rem', borderRadius: '12px', background: 'var(--surface-strong)', border: '1px solid var(--line-strong)' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase' }}>{t("vote.allocation_board")}</div>
              <div style={{ fontSize: '0.9rem', fontWeight: 700 }}>{bus.board_at}</div>
            </div>
            <div style={{ padding: '0.75rem', borderRadius: '12px', background: 'var(--surface-strong)', border: '1px solid var(--line-strong)' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase' }}>{t("vote.allocation_alight")}</div>
              <div style={{ fontSize: '0.9rem', fontWeight: 700 }}>{bus.alight_at}</div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '1.25rem', flexWrap: 'wrap', fontSize: '0.85rem', color: 'var(--text-3)', marginBottom: '1rem' }}>
            {bus.trips_per_day != null && <span><strong style={{ color: 'var(--text)' }}>{bus.trips_per_day}</strong> {t("vote.allocation_trips_per_day")}</span>}
            {bus.duration_minutes != null && <span><strong style={{ color: 'var(--text)' }}>{Math.round(bus.duration_minutes)}</strong> min</span>}
            {bus.distance_km != null && <span><strong style={{ color: 'var(--text)' }}>{bus.distance_km}</strong> km</span>}
            {bus.stops_on_journey != null && <span><strong style={{ color: 'var(--text)' }}>{bus.stops_on_journey}</strong> {t("vote.allocation_stops")}</span>}
          </div>

          {bus.first_departures?.length > 0 && (
            <div style={{ marginBottom: '1rem' }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-3)', fontWeight: 700, textTransform: 'uppercase', marginBottom: '0.4rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <Clock size={12} /> {t("vote.allocation_first_departures")}
              </div>
              <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                {bus.first_departures.map((departure: string, index: number) => (
                  <span key={`${departure}-${index}`} style={{ padding: '3px 10px', borderRadius: '8px', fontSize: '0.8rem', fontWeight: 700, background: 'var(--surface-strong)', border: '1px solid var(--line-strong)' }}>
                    {timeLabel(departure)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* A transfer journey is two buses. Spell both out rather than
              letting the single badge above stand in for the whole trip. */}
          {bus.legs?.length > 1 && (
            <div style={{ marginBottom: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {bus.legs.map((leg: any, index: number) => (
                <div key={`${leg.bus_number}-${index}`} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '0.6rem 0.85rem', borderRadius: '10px', background: 'var(--surface-strong)', border: '1px solid var(--line-strong)' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-3)' }}>{index + 1}</span>
                  <span className="bus-badge" style={{ fontSize: '0.8rem', padding: '0.2rem 0.6rem', minWidth: 'auto' }}>{leg.bus_number}</span>
                  <span style={{ fontSize: '0.82rem' }}>{leg.from_stop} → {leg.to_stop}</span>
                </div>
              ))}
            </div>
          )}

          <div style={{ paddingTop: '1rem', borderTop: '1px solid var(--line-strong)', display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
            {/* What the votes for this pair actually add up to. */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', color: 'var(--text-3)' }}>
              <Users size={14} />
              {demand.available === false ? (
                <span>{demand.note}</span>
              ) : (
                <span>
                  {t("vote.allocation_demand")}: <strong style={{ color: 'var(--text)' }}>{demand.genuine_votes ?? 0}</strong>
                  {" "}({demand.unique_voters ?? 0} {t("vote.allocation_voters")}
                  {demand.your_votes ? `, ${demand.your_votes} ${t("vote.allocation_your_votes")}` : ""})
                  {" · "}{demand.period_days}d
                </span>
              )}
            </div>

            {/* Strictly what POST /depot/deploy-bus recorded: a human reviewed
                this route. Not a dispatch — no bus is sent anywhere by this app. */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
              {review ? (
                <>
                  <CheckCircle size={14} style={{ color: '#10b981', flexShrink: 0 }} />
                  <span style={{ color: '#10b981', fontWeight: 600 }}>
                    {t("vote.allocation_depot_reviewed")} · {review.route_number} · {review.at}
                    {review.note ? ` — ${review.note}` : ""}
                  </span>
                </>
              ) : (
                <>
                  <Clock size={14} style={{ color: 'var(--text-3)', flexShrink: 0 }} />
                  <span className="text-muted">{t("vote.allocation_depot_pending")}</span>
                </>
              )}
            </div>

            {allocation.other_options?.length > 0 && (
              <div style={{ fontSize: '0.82rem', color: 'var(--text-3)' }}>
                {t("vote.allocation_other")}:{" "}
                {allocation.other_options.map((option: any) => option.bus_chain).join(", ")}
              </div>
            )}

            <Link
              to={`/predict?from=${encodeURIComponent(allocation.query.current_stop)}&to=${encodeURIComponent(allocation.query.destination)}`}
              className="bento-btn"
              style={{ alignSelf: 'flex-start', padding: '6px 14px', fontSize: '0.82rem', height: 'auto', textDecoration: 'none', marginTop: '0.25rem' }}
            >
              <Map size={13} style={{ marginRight: '5px' }} /> {t("vote.allocation_view_route")}
            </Link>

            <p className="text-muted" style={{ margin: '0.25rem 0 0 0', fontSize: '0.75rem', lineHeight: 1.45 }}>
              {allocation.source}
            </p>
          </div>
        </>
      )}
    </motion.div>
  );
}
