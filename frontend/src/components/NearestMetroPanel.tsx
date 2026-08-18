import { useEffect, useState } from "react";
import { MapPin, Navigation, Map, Footprints, Car, ArrowRight, Train, Sparkles, RefreshCw, Maximize2, X, ZoomIn, ZoomOut } from "lucide-react";
import { AutocompleteInput } from "./AutocompleteInput";
import { api } from "../services/api";
import type { MetroStation } from "../types/api";
import { MetroMapModal } from "./MetroMapModal";

type Props = {
  initialStop?: string;
  title?: string;
  showSearch?: boolean;
};

export function NearestMetroPanel({ initialStop = "Whitefield ACP Police Station", title = "Nearest Metro Station to Destination", showSearch = true }: Props) {
  const [stop, setStop] = useState(initialStop);
  const [loading, setLoading] = useState(false);
  const [nearestStations, setNearestStations] = useState<MetroStation[]>([]);
  const [showMapModal, setShowMapModal] = useState(false);
  const [inlineMapOpen, setInlineMapOpen] = useState(false);
  const [inlineZoom, setInlineZoom] = useState(100);

  const fetchNearest = async (queryStop: string) => {
    if (!queryStop.trim()) return;
    setLoading(true);
    try {
      const res = await api.getNearestMetro(queryStop, undefined, undefined, 3);
      setNearestStations(res.nearest_metro_stations || []);
    } catch (err) {
      console.error("Failed to fetch nearest metro:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (initialStop) {
      setStop(initialStop);
      fetchNearest(initialStop);
    }
  }, [initialStop]);

  const pdfViewUrl = "./metro_map_2025.pdf#toolbar=0&navpanes=0&scrollbar=1";

  return (
    <div
      className="bento-card"
      style={{
        padding: "1.5rem",
        marginBottom: "1.5rem",
        position: "relative",
        overflow: "hidden",
        border: "1px solid var(--line-strong)",
      }}
    >
      {/* Background glow accent */}
      <div
        style={{
          position: "absolute",
          top: -30,
          right: -30,
          width: "180px",
          height: "180px",
          background: "radial-gradient(circle, rgba(124, 58, 237, 0.15) 0%, transparent 70%)",
          borderRadius: "50%",
          pointerEvents: "none",
        }}
      />

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "0.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          <div
            style={{
              padding: "6px 10px",
              borderRadius: "10px",
              background: "rgba(124, 58, 237, 0.15)",
              color: "var(--brand-2)",
              display: "flex",
              alignItems: "center",
              gap: "6px",
            }}
          >
            <Train size={18} />
          </div>
          <div>
            <h3 className="bento-title" style={{ fontSize: "1.1rem", margin: 0 }}>
              {title}
            </h3>
            <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
              Namma Metro connection & last-mile transfer
            </span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => setInlineMapOpen(!inlineMapOpen)}
            className="bento-btn secondary"
            style={{
              fontSize: "0.82rem",
              padding: "6px 14px",
              borderRadius: "12px",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              fontWeight: 600,
            }}
          >
            <Map size={15} /> {inlineMapOpen ? "Hide Map" : "View Map"}
          </button>

          <button
            type="button"
            onClick={() => setShowMapModal(true)}
            className="bento-btn"
            style={{
              fontSize: "0.82rem",
              padding: "6px 14px",
              borderRadius: "12px",
              background: "var(--gradient-brand-subtle)",
              border: "1px solid var(--brand)",
              color: "var(--brand-strong)",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              fontWeight: 700,
            }}
          >
            <Maximize2 size={15} /> Full Screen View
          </button>
        </div>
      </div>

      {/* Inline Metro Map Container */}
      {inlineMapOpen && (
        <div
          style={{
            marginBottom: "1.25rem",
            borderRadius: "16px",
            border: "1px solid var(--line-strong)",
            overflow: "hidden",
            background: "#12131C",
            position: "relative",
          }}
        >
          {/* Controls Bar for Inline View */}
          <div
            style={{
              padding: "0.6rem 1rem",
              background: "var(--surface-strong)",
              borderBottom: "1px solid var(--line-strong)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "8px",
              flexWrap: "wrap",
            }}
          >
            <span style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--text)" }}>
              🗺️ Bengaluru Metro Map 2025
            </span>

            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              {/* Minus (-) Zoom Out */}
              <button
                type="button"
                className="bento-btn secondary"
                onClick={() => setInlineZoom((z) => Math.max(z - 25, 75))}
                title="Zoom Out (-)"
                style={{ padding: "4px 10px", fontSize: "0.82rem", fontWeight: 700, borderRadius: "8px" }}
              >
                -
              </button>

              <span style={{ fontSize: "0.78rem", fontWeight: 700, padding: "0 4px", color: "var(--text-muted)" }}>
                {inlineZoom}%
              </span>

              {/* Plus (+) Zoom In */}
              <button
                type="button"
                className="bento-btn secondary"
                onClick={() => setInlineZoom((z) => Math.min(z + 25, 250))}
                title="Zoom In (+)"
                style={{ padding: "4px 10px", fontSize: "0.82rem", fontWeight: 700, borderRadius: "8px" }}
              >
                +
              </button>

              <div style={{ width: "1px", height: "18px", background: "var(--line-strong)", margin: "0 2px" }} />

              {/* Full screen view button */}
              <button
                type="button"
                className="bento-btn secondary"
                onClick={() => setShowMapModal(true)}
                title="Full Screen View"
                style={{ padding: "4px 10px", fontSize: "0.82rem", fontWeight: 600, borderRadius: "8px", display: "inline-flex", alignItems: "center", gap: "4px" }}
              >
                <Maximize2 size={13} /> Full Screen
              </button>

              {/* Close button */}
              <button
                type="button"
                onClick={() => setInlineMapOpen(false)}
                title="Close Map"
                style={{
                  background: "rgba(239, 68, 68, 0.15)",
                  color: "#ef4444",
                  border: "1px solid rgba(239,68,68,0.3)",
                  borderRadius: "8px",
                  padding: "4px 8px",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                  fontSize: "0.8rem",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                <X size={14} /> Close
              </button>
            </div>
          </div>

          {/* Map display */}
          <div style={{ height: "420px", overflow: "auto", position: "relative" }}>
            <div
              style={{
                width: `${inlineZoom}%`,
                height: `${inlineZoom}%`,
                minWidth: "100%",
                minHeight: "100%",
                transition: "width 0.2s ease, height 0.2s ease",
              }}
            >
              <object data={pdfViewUrl} type="application/pdf" width="100%" height="100%" style={{ border: "none" }}>
                <iframe src={pdfViewUrl} width="100%" height="100%" style={{ border: "none" }} title="Bengaluru Metro Map 2025" />
              </object>
            </div>
          </div>
        </div>
      )}

      {/* Optional Search Input */}
      {showSearch && (
        <div style={{ marginBottom: "1.25rem", display: "flex", gap: "8px", alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <AutocompleteInput
              label="Select Destination Bus Stop"
              value={stop}
              kind="destination"
              placeholder="e.g. Marathahalli or Whitefield"
              onChange={(val) => {
                setStop(val);
                fetchNearest(val);
              }}
            />
          </div>
          <button
            type="button"
            className="bento-btn secondary"
            onClick={() => fetchNearest(stop)}
            style={{ height: "46px", padding: "0 1rem", borderRadius: "12px" }}
            title="Search Nearest Metro"
          >
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      )}

      {/* Results */}
      {nearestStations.length === 0 ? (
        <div style={{ padding: "1rem", textAlign: "center", background: "var(--surface-strong)", borderRadius: "12px", color: "var(--text-muted)", fontSize: "0.88rem" }}>
          {loading ? "Calculating nearest Namma Metro station..." : "Select a bus stop to see the nearest Metro station"}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {nearestStations.map((st, index) => {
            const isPrimary = index === 0;
            const lineColor = st.line_color || (st.line.includes("Green") ? "#16A34A" : st.line.includes("Yellow") ? "#CA8A04" : "#7E22CE");

            return (
              <div
                key={st.station_code || index}
                style={{
                  padding: "1rem 1.25rem",
                  background: isPrimary ? "var(--surface-strong)" : "var(--surface-muted)",
                  borderRadius: "14px",
                  border: `1px solid ${isPrimary ? "var(--brand)" : "var(--line-strong)"}`,
                  boxShadow: isPrimary ? "var(--shadow-sm)" : "none",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: "0.75rem",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", minWidth: "220px" }}>
                  <div
                    style={{
                      width: "12px",
                      height: "44px",
                      borderRadius: "6px",
                      background: lineColor,
                      flexShrink: 0,
                    }}
                  />
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ fontWeight: 700, fontSize: "1rem", color: "var(--text)" }}>
                        {st.station_name}
                      </span>
                      {st.is_interchange && (
                        <span
                          style={{
                            fontSize: "0.7rem",
                            fontWeight: 700,
                            padding: "2px 8px",
                            borderRadius: "10px",
                            background: "rgba(124, 58, 237, 0.15)",
                            color: "var(--brand-2)",
                            border: "1px solid var(--brand-2)",
                          }}
                        >
                          🔄 Interchange Hub
                        </span>
                      )}
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: "10px", marginTop: "4px", fontSize: "0.82rem", color: "var(--text-muted)" }}>
                      <span style={{ fontWeight: 600, color: lineColor }}>● {st.line}</span>
                      <span>• Station Code: {st.station_code}</span>
                    </div>
                  </div>
                </div>

                {/* Distance & Travel Time Badges */}
                <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                  <div
                    style={{
                      padding: "6px 12px",
                      borderRadius: "10px",
                      background: "rgba(16, 185, 129, 0.12)",
                      border: "1px solid rgba(16, 185, 129, 0.3)",
                      color: "#10b981",
                      fontSize: "0.82rem",
                      fontWeight: 700,
                      display: "flex",
                      alignItems: "center",
                      gap: "5px",
                    }}
                  >
                    <Navigation size={13} /> {st.distance_km} km ({st.distance_meters}m)
                  </div>

                  <div
                    style={{
                      padding: "6px 12px",
                      borderRadius: "10px",
                      background: "var(--surface-glass)",
                      border: "1px solid var(--line-strong)",
                      fontSize: "0.82rem",
                      fontWeight: 600,
                      display: "flex",
                      alignItems: "center",
                      gap: "5px",
                    }}
                  >
                    <Footprints size={13} style={{ color: "var(--brand)" }} /> {st.walking_minutes} min walk
                  </div>

                  <div
                    style={{
                      padding: "6px 12px",
                      borderRadius: "10px",
                      background: "var(--surface-glass)",
                      border: "1px solid var(--line-strong)",
                      fontSize: "0.82rem",
                      fontWeight: 600,
                      display: "flex",
                      alignItems: "center",
                      gap: "5px",
                    }}
                  >
                    <Car size={13} style={{ color: "var(--brand-2)" }} /> {st.auto_minutes} min auto
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Metro Map Modal */}
      <MetroMapModal isOpen={showMapModal} onClose={() => setShowMapModal(false)} />
    </div>
  );
}
