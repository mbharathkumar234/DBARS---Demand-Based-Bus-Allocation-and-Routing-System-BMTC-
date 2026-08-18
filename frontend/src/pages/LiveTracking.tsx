import { useEffect, useState, useRef } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { SearchInputWithHistory } from "../components/SearchInputWithHistory";
import { motion } from "framer-motion";
import { Navigation, RefreshCw, Bus, Gauge, Users, MapPin, ArrowLeft } from "lucide-react";
import { useLanguage } from "../contexts/LanguageContext";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { apiFetch } from "../lib/apiClient";

interface BusPosition {
  bus_number: string;
  route_id: string;
  latitude: number;
  longitude: number;
  speed_kmh: number;
  occupancy_pct: number;
  heading: number;
  next_stop: string;
  direction: string;
}

export default function LiveTracking() {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const highlightBus = searchParams.get("bus");
  const [buses, setBuses] = useState<BusPosition[]>([]);
  const [selected, setSelected] = useState<BusPosition | null>(null);
  const [searchQuery, setSearchQuery] = useState(highlightBus || "");
  const [loading, setLoading] = useState(true);
  const [trackingLabel, setTrackingLabel] = useState("Simulated / Demo Tracking");
  const mapRef = useRef<HTMLDivElement>(null);
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    // Ask the backend what's actually powering this page, rather than
    // asserting it in the UI ourselves -- see GET /tracking/source, which
    // always honestly reports "simulation" (there is no real BMTC vehicle
    // feed wired into this project). Keeping the label backend-driven
    // means this can't drift out of sync with reality the way the old
    // hardcoded "Live VTU Tracking" claim did.
    apiFetch("/tracking/source")
      .then((res) => res.json())
      .then((data) => setTrackingLabel(data.label || "Simulated / Demo Tracking"))
      .catch(() => {});
  }, []);

  const selectedRef = useRef<BusPosition | null>(null);
  selectedRef.current = selected;

  const fetchBuses = async () => {
    try {
      // Fetch bus positions (server ticks on read or timer)
      const res = await apiFetch(`/tracking/buses`);
      const data = await res.json();
      const busList = data.buses || [];
      setBuses(busList);
      if (highlightBus && !selectedRef.current) {
        const match = busList.find((b: BusPosition) => b.bus_number.toUpperCase() === highlightBus.toUpperCase());
        if (match) setSelected(match);
      }
    } catch (err) {
      console.error("Tracking fetch failed:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBuses();
    intervalRef.current = window.setInterval(fetchBuses, 10000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [highlightBus]);

  const occupancyColor = (pct: number) => pct < 40 ? "#10b981" : pct < 70 ? "#f59e0b" : "#ef4444";

  const handleSearch = () => {
    if (!searchQuery.trim()) return;
    const q = searchQuery.toUpperCase();
    const match = buses.find(b => b.bus_number.toUpperCase().includes(q) || b.route_id.toUpperCase().includes(q));
    if (match) setSelected(match);
  };

  return (
    <div className="page-container">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="tracking-page">
        <div className="page-header" style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
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
          <Navigation size={24} className="text-accent" style={{ flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <h1 style={{ margin: 0 }}>{t("track.title")}</h1>
            <p className="text-muted" style={{ margin: 0, fontSize: '0.9rem' }}>{t("track.subtitle")}</p>
          </div>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ width: '220px' }}>
              <SearchInputWithHistory
                storageKey="bmtc_history_live_tracking"
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder="Search bus number..."
                onSubmit={handleSearch}
              />
            </div>
            <button className="secondary-button" onClick={fetchBuses}>
              <RefreshCw size={14} /> {t("track.refresh")}
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <div className="demo-badge" style={{ margin: 0 }}>
            🧪 {trackingLabel} — {buses.length} Buses Shown
          </div>
        </div>

        <div className="tracking-layout">
          {/* Map placeholder — Leaflet would be integrated here */}
          <div className="tracking-map card" ref={mapRef}>
            <div className="map-container">
              {loading ? (
                <div className="map-loading">{t("common.loading")}</div>
              ) : (
                <div className="map-visual" style={{ width: "100%", height: "100%" }}>
                  <MapContainer center={[12.9716, 77.5946]} zoom={12} style={{ width: "100%", height: "100%", borderRadius: "12px", zIndex: 0 }}>
                    <TileLayer
                      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                    {buses.map((bus, i) => {
                      const isSelected = selected?.bus_number === bus.bus_number && selected?.route_id === bus.route_id;
                      const icon = L.divIcon({
                        className: "custom-bus-icon",
                        html: `<div style="transform: rotate(${bus.heading}deg); width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));">
                                 <svg viewBox="0 0 24 24" fill="${occupancyColor(bus.occupancy_pct)}" stroke="${isSelected ? '#fff' : '#333'}" stroke-width="${isSelected ? 2 : 1.5}" width="24" height="24">
                                   <path d="M12 2L20 20L12 17L4 20L12 2Z" />
                                 </svg>
                               </div>`,
                        iconSize: [24, 24],
                        iconAnchor: [12, 12],
                      });
                      
                      return (
                        <Marker 
                          key={`${bus.bus_number}-${bus.route_id}-${i}`}
                          position={[bus.latitude, bus.longitude]} 
                          icon={icon}
                          eventHandlers={{ click: () => setSelected(bus) }}
                          zIndexOffset={isSelected ? 1000 : 0}
                        >
                          <Popup>
                            <div style={{ textAlign: "center" }}>
                              <strong>{bus.bus_number}</strong><br/>
                              {bus.speed_kmh} km/h • {bus.occupancy_pct}% full
                            </div>
                          </Popup>
                        </Marker>
                      );
                    })}
                  </MapContainer>
                </div>
              )}
            </div>
          </div>

          {/* Bus list / details */}
          <div className="tracking-sidebar">
            {selected ? (
              <div className="bus-detail-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <div className="bus-badge" style={{ fontSize: '1.1rem', padding: '0.4rem 0.9rem' }}>
                      {selected.bus_number}
                    </div>
                    <div>
                      <h3 style={{ margin: 0, fontSize: '1.05rem', lineHeight: '1.2' }}>Route {selected.route_id}</h3>
                      <span style={{ fontSize: '0.78rem', color: 'var(--text-3)' }}>{selected.direction}</span>
                    </div>
                  </div>
                  <button className="secondary-button" onClick={() => setSelected(null)} style={{ padding: '0.4rem 0.8rem', fontSize: '0.82rem' }}>
                    {t("common.back")}
                  </button>
                </div>

                <div className="bus-stats-grid">
                  <div className="bus-stat">
                    <Gauge size={18} className="stat-icon" />
                    <span className="stat-value">{selected.speed_kmh} <small style={{ fontSize: '0.65rem' }}>km/h</small></span>
                    <span className="stat-label">{t("track.speed")}</span>
                  </div>
                  <div className="bus-stat">
                    <Users size={18} className="stat-icon" style={{ color: occupancyColor(selected.occupancy_pct) }} />
                    <span className="stat-value" style={{ color: occupancyColor(selected.occupancy_pct) }}>
                      {selected.occupancy_pct}%
                    </span>
                    <span className="stat-label">{t("track.occupancy")}</span>
                  </div>
                  <div className="bus-stat">
                    <MapPin size={18} className="stat-icon" />
                    <span className="stat-value" style={{ fontSize: '0.82rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '85px' }}>
                      {selected.next_stop}
                    </span>
                    <span className="stat-label">{t("track.next_stop")}</span>
                  </div>
                </div>

                {/* Route Timeline View */}
                <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid var(--line-strong)' }}>
                  <h4 style={{ fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--text-3)', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Navigation size={14} className="text-accent" /> Live Route Progress
                  </h4>
                  
                  <div className="route-timeline">
                    <div className="timeline-step">
                      <div className="timeline-node board" />
                      <div className="timeline-content">
                        <span className="timeline-stop-name">Route Origin</span>
                        <span className="timeline-tag">En Route</span>
                      </div>
                    </div>
                    <div className="timeline-step">
                      <div className="timeline-node intermediate" />
                      <div className="timeline-content">
                        <span className="timeline-stop-name" style={{ color: 'var(--brand)' }}>{selected.next_stop}</span>
                        <span className="timeline-tag" style={{ color: 'var(--brand-strong)', fontWeight: 600 }}>Next Arriving Stop</span>
                      </div>
                    </div>
                    <div className="timeline-step">
                      <div className="timeline-node alight" />
                      <div className="timeline-content">
                        <span className="timeline-stop-name">Final Terminus</span>
                        <span className="timeline-tag">{selected.direction}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="bus-list-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Bus size={18} className="text-accent" /> Active Buses ({buses.length})
                  </h3>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-3)', background: 'var(--surface-strong)', padding: '2px 8px', borderRadius: '10px', border: '1px solid var(--line-strong)' }}>
                    Simulated
                  </span>
                </div>
                
                <div className="bus-scroll-list">
                  {buses.slice(0, 35).map((bus, i) => (
                    <div
                      key={`${bus.bus_number}-${bus.route_id}-${i}`}
                      className="bus-list-item"
                      onClick={() => setSelected(bus)}
                    >
                      <div className="bus-badge">{bus.bus_number}</div>
                      <div className="bus-list-info">
                        <span className="bus-list-stop">
                          <Navigation size={12} style={{ color: 'var(--brand)', transform: 'rotate(90deg)', flexShrink: 0 }} />
                          {bus.next_stop}
                        </span>
                        <span className="bus-list-speed">
                          <Gauge size={12} /> {bus.speed_kmh} km/h
                        </span>
                      </div>
                      <div 
                        className="occupancy-dot-pill" 
                        style={{ 
                          background: `${occupancyColor(bus.occupancy_pct)}18`, 
                          color: occupancyColor(bus.occupancy_pct),
                          border: `1px solid ${occupancyColor(bus.occupancy_pct)}40`
                        }}
                      >
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: occupancyColor(bus.occupancy_pct) }} />
                        {bus.occupancy_pct}%
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}