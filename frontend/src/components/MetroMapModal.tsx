import { useState } from "react";
import { X, Maximize2, Minimize2, Map, ZoomIn, ZoomOut, Eye } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

type Props = {
  isOpen: boolean;
  onClose: () => void;
};

export function MetroMapModal({ isOpen, onClose }: Props) {
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(100);

  // Serve static PDF with toolbar disabled (#toolbar=0) to prevent browser PDF save/download
  const pdfViewUrl = "./metro_map_2025.pdf#toolbar=0&navpanes=0&scrollbar=1";

  if (!isOpen) return null;

  const handleZoomIn = () => setZoomLevel((prev) => Math.min(prev + 25, 250));
  const handleZoomOut = () => setZoomLevel((prev) => Math.max(prev - 25, 75));
  const handleResetZoom = () => setZoomLevel(100);

  return (
    <AnimatePresence>
      <div
        className="modal-overlay"
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 99999,
          background: "rgba(0, 0, 0, 0.85)",
          backdropFilter: "blur(10px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: isFullScreen ? 0 : "1.25rem",
        }}
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 15 }}
          transition={{ duration: 0.2 }}
          onClick={(e) => e.stopPropagation()}
          className="bento-card"
          style={{
            width: isFullScreen ? "100vw" : "100%",
            maxWidth: isFullScreen ? "100vw" : "1150px",
            height: isFullScreen ? "100vh" : "88vh",
            borderRadius: isFullScreen ? 0 : "24px",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            background: "var(--bg)",
            border: "1px solid var(--line-strong)",
            boxShadow: "0 25px 60px rgba(0,0,0,0.6)",
          }}
        >
          {/* Header Bar */}
          <div
            style={{
              padding: "0.9rem 1.5rem",
              background: "var(--surface-strong)",
              borderBottom: "1px solid var(--line-strong)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "1rem",
              flexWrap: "wrap",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <div
                style={{
                  width: 38,
                  height: 38,
                  borderRadius: 12,
                  background: "linear-gradient(135deg, #7C3AED 0%, #00E5C8 100%)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "white",
                  boxShadow: "0 4px 12px rgba(124, 58, 237, 0.3)",
                }}
              >
                <Map size={20} />
              </div>
              <div>
                <h3 className="bento-title" style={{ fontSize: "1.15rem", margin: 0, display: "flex", alignItems: "center", gap: "8px" }}>
                  Bengaluru Namma Metro Map 2025
                  <span
                    style={{
                      fontSize: "0.72rem",
                      fontWeight: 700,
                      padding: "2px 8px",
                      borderRadius: "12px",
                      background: "rgba(16, 185, 129, 0.15)",
                      color: "#10b981",
                      border: "1px solid #10b981",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    <Eye size={12} /> View-Only Mode
                  </span>
                </h3>
                <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
                  Purple, Green, Yellow & Airport Lines Network Map
                </span>
              </div>
            </div>

            {/* View & Enlarge Controls */}
            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
              {/* Minus (-) Zoom Out Button */}
              <button
                type="button"
                className="bento-btn secondary"
                onClick={handleZoomOut}
                title="Zoom Out (-)"
                style={{ padding: "6px 12px", fontSize: "0.85rem", fontWeight: 700, borderRadius: "10px", display: "inline-flex", alignItems: "center", gap: "4px" }}
              >
                <ZoomOut size={15} />
                <span>- Zoom Out</span>
              </button>

              {/* Reset Zoom Indicator */}
              <button
                type="button"
                onClick={handleResetZoom}
                style={{
                  background: "var(--surface-glass)",
                  border: "1px solid var(--line-strong)",
                  color: "var(--text)",
                  fontSize: "0.8rem",
                  fontWeight: 700,
                  padding: "6px 10px",
                  borderRadius: "10px",
                  cursor: "pointer",
                }}
                title="Reset Zoom"
              >
                {zoomLevel}%
              </button>

              {/* Plus (+) Zoom In Button */}
              <button
                type="button"
                className="bento-btn secondary"
                onClick={handleZoomIn}
                title="Zoom In (+)"
                style={{ padding: "6px 12px", fontSize: "0.85rem", fontWeight: 700, borderRadius: "10px", display: "inline-flex", alignItems: "center", gap: "4px" }}
              >
                <ZoomIn size={15} />
                <span>+ Zoom In</span>
              </button>

              {/* Full Screen View Button */}
              <button
                type="button"
                className="bento-btn"
                onClick={() => setIsFullScreen(!isFullScreen)}
                style={{
                  fontSize: "0.82rem",
                  padding: "6px 14px",
                  borderRadius: "10px",
                  background: "var(--gradient-brand)",
                  color: "white",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "6px",
                  fontWeight: 600,
                }}
                title={isFullScreen ? "Exit Full Screen" : "Full Screen View"}
              >
                {isFullScreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                <span>{isFullScreen ? "Exit Full Screen" : "Full Screen View"}</span>
              </button>

              {/* Close Button */}
              <button
                type="button"
                className="bento-btn"
                onClick={onClose}
                title="Close Viewer"
                style={{ padding: "6px 14px", background: "rgba(239, 68, 68, 0.15)", color: "#ef4444", border: "1px solid rgba(239,68,68,0.4)", borderRadius: "10px", display: "inline-flex", alignItems: "center", gap: "6px", fontWeight: 700, fontSize: "0.82rem" }}
              >
                <X size={16} />
                <span>Close</span>
              </button>
            </div>
          </div>

          {/* View-Only Viewer Container with Zoom Scaling */}
          <div
            style={{
              flex: 1,
              width: "100%",
              background: "#12131C",
              position: "relative",
              overflow: "auto",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {/* Floating Top-Right Controls Overlay */}
            <div
              style={{
                position: "absolute",
                top: "16px",
                right: "16px",
                zIndex: 1000,
                display: "flex",
                alignItems: "center",
                gap: "8px",
                background: "rgba(18, 19, 28, 0.9)",
                backdropFilter: "blur(10px)",
                padding: "6px 12px",
                borderRadius: "14px",
                border: "1px solid var(--line-strong)",
                boxShadow: "0 10px 30px rgba(0,0,0,0.6)",
              }}
            >
              {/* Minus (-) button */}
              <button
                type="button"
                onClick={handleZoomOut}
                title="Zoom Out (-)"
                style={{
                  background: "var(--surface-strong)",
                  border: "1px solid var(--line-strong)",
                  color: "var(--text)",
                  width: "34px",
                  height: "34px",
                  borderRadius: "10px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 800,
                  fontSize: "1.2rem",
                  cursor: "pointer",
                }}
              >
                -
              </button>

              {/* Reset Zoom */}
              <button
                type="button"
                onClick={handleResetZoom}
                title="Reset Zoom (100%)"
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--text-muted)",
                  fontSize: "0.8rem",
                  fontWeight: 700,
                  padding: "0 6px",
                  cursor: "pointer",
                }}
              >
                {zoomLevel}%
              </button>

              {/* Plus (+) button */}
              <button
                type="button"
                onClick={handleZoomIn}
                title="Zoom In (+)"
                style={{
                  background: "var(--surface-strong)",
                  border: "1px solid var(--line-strong)",
                  color: "var(--text)",
                  width: "34px",
                  height: "34px",
                  borderRadius: "10px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 800,
                  fontSize: "1.2rem",
                  cursor: "pointer",
                }}
              >
                +
              </button>

              <div style={{ width: "1px", height: "22px", background: "var(--line-strong)", margin: "0 4px" }} />

              {/* Full screen view button */}
              <button
                type="button"
                onClick={() => setIsFullScreen(!isFullScreen)}
                title={isFullScreen ? "Exit Full Screen" : "Full Screen View"}
                style={{
                  background: "var(--surface-strong)",
                  border: "1px solid var(--line-strong)",
                  color: "var(--brand-2)",
                  height: "34px",
                  padding: "0 12px",
                  borderRadius: "10px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  fontWeight: 700,
                  fontSize: "0.82rem",
                  cursor: "pointer",
                }}
              >
                {isFullScreen ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                <span>{isFullScreen ? "Exit Full Screen" : "Full Screen"}</span>
              </button>

              {/* Close button */}
              <button
                type="button"
                onClick={onClose}
                title="Close Map"
                style={{
                  background: "rgba(239, 68, 68, 0.2)",
                  border: "1px solid rgba(239, 68, 68, 0.4)",
                  color: "#ef4444",
                  height: "34px",
                  padding: "0 12px",
                  borderRadius: "10px",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  fontWeight: 700,
                  fontSize: "0.82rem",
                  cursor: "pointer",
                }}
              >
                <X size={15} />
                <span>Close</span>
              </button>
            </div>

            <div
              style={{
                width: `${zoomLevel}%`,
                height: `${zoomLevel}%`,
                minWidth: "100%",
                minHeight: "100%",
                transition: "width 0.2s ease, height 0.2s ease",
              }}
            >
              <object
                data={pdfViewUrl}
                type="application/pdf"
                width="100%"
                height="100%"
                style={{ border: "none" }}
              >
                <iframe
                  src={pdfViewUrl}
                  width="100%"
                  height="100%"
                  style={{ border: "none" }}
                  title="Bengaluru Metro Map 2025 (View-Only)"
                />
              </object>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
