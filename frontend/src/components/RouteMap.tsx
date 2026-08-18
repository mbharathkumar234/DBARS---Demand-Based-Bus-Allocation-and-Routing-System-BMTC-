import { useEffect, useMemo } from "react";
import { createPortal } from "react-dom";
import { MapContainer, TileLayer, Marker, Polyline, Popup, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { Maximize2, Minimize2 } from "lucide-react";

type Coordinate = { stop: string; lat: number | null; lon: number | null };
type Leg = { bus_number?: string; from_stop?: string; to_stop?: string; route_coordinates?: Coordinate[] };

type Props = {
  coordinates?: Coordinate[];
  /** Present on a transfer journey. Each leg is drawn as its own line so the
   *  changeover is visible instead of being hidden inside one continuous
   *  stroke that implies a single bus. */
  legs?: Leg[];
  routePath?: string[];
  expanded: boolean;
  onToggleExpand: () => void;
  collapsedHeight?: number;
};

// Distinct colours per leg. Deliberately high-contrast rather than a gradient:
// the question a rider asks of this map is "where do I get off and change",
// and two shades of the same colour do not answer it.
const LEG_COLOURS = ["#00e5c8", "#f59e0b", "#8b5cf6", "#ef4444"];

const dotIcon = (color: string, label: string, size = 16) =>
  L.divIcon({
    className: "custom-neon-marker",
    html:
      `<div aria-label="${label}" role="img" style="width:${size}px;height:${size}px;background:${color};` +
      `border-radius:50%;box-shadow:0 0 10px ${color},0 0 20px ${color};border:2px solid white"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });

/**
 * Keep Leaflet's idea of its own size in step with the container.
 *
 * Leaflet measures its container once, at mount, and caches the result. Any
 * later change to the container's size -- a window resize, a rotation, a
 * layout shift -- leaves it drawing tiles for dimensions that no longer exist.
 *
 * invalidateSize() re-measures. It runs after a frame so the browser has
 * applied the new layout first, and re-fits the route afterwards so a resize
 * shows the journey rather than an arbitrary crop of it.
 *
 * (The full-screen mode collapsing to a letterbox strip was a separate and
 * larger problem -- a CSS containing block, not a stale measurement. See the
 * portal at the bottom of this file.)
 */
function MapBehaviour({ expanded, bounds }: { expanded: boolean; bounds: [number, number][] }) {
  const map = useMap();

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      map.invalidateSize();
      if (bounds.length > 0) {
        map.fitBounds(L.latLngBounds(bounds), { padding: [40, 40] });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [expanded, map, bounds]);

  // Interaction handlers must be toggled imperatively. MapContainer's props
  // (scrollWheelZoom, zoomControl, ...) are read ONCE when Leaflet is
  // constructed and ignored on every later render, so passing
  // `scrollWheelZoom={expanded}` silently did nothing when the map expanded --
  // which is why the full-screen map could not be zoomed.
  useEffect(() => {
    // Collapsed, the map is a thumbnail inside a scrolling page: capturing the
    // wheel there would trap the reader's scroll. Expanded, it is the only
    // thing on screen and the wheel should zoom.
    if (expanded) {
      map.scrollWheelZoom.enable();
      map.dragging.enable();
      map.doubleClickZoom.enable();
      map.touchZoom.enable();
      map.keyboard.enable();
    } else {
      map.scrollWheelZoom.disable();
    }
  }, [expanded, map]);

  // A container can also change size without this component re-rendering --
  // a window resize, a phone rotating, a sidebar opening.
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(map.getContainer());
    const onOrientation = () => map.invalidateSize();
    window.addEventListener("orientationchange", onOrientation);
    return () => {
      observer.disconnect();
      window.removeEventListener("orientationchange", onOrientation);
    };
  }, [map]);

  return null;
}

export function RouteMap({
  coordinates = [],
  legs,
  routePath = [],
  expanded,
  onToggleExpand,
  collapsedHeight = 250,
}: Props) {
  // Escape closes, and the page behind stops scrolling. Both are what a
  // full-screen overlay is expected to do, and neither is possible for the
  // caller to add from outside the component.
  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onToggleExpand();
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [expanded, onToggleExpand]);

  const isPoint = (c: Coordinate) => c.lat !== null && c.lon !== null;

  // Memoised so the arrays keep a stable identity between renders. Without
  // this, `allPoints` was a fresh array every render, the fitBounds effect
  // below saw a changed dependency each time, and the map snapped back to the
  // whole route the instant anything re-rendered -- which reads to a user as
  // "I cannot zoom in".
  const legLines = useMemo<{ colour: string; points: [number, number][]; leg?: Leg }[]>(
    () =>
      (legs?.length
        ? legs.map((leg, index) => ({
            colour: LEG_COLOURS[index % LEG_COLOURS.length],
            points: (leg.route_coordinates || [])
              .filter(isPoint)
              .map((c) => [c.lat as number, c.lon as number] as [number, number]),
            leg,
          }))
        : [{
            colour: LEG_COLOURS[0],
            points: coordinates
              .filter(isPoint)
              .map((c) => [c.lat as number, c.lon as number] as [number, number]),
          }]
      ).filter((line) => line.points.length >= 2),
    [legs, coordinates],
  );

  const allPoints = useMemo(() => legLines.flatMap((line) => line.points), [legLines]);

  // Without coordinates, fall back to the plain stop list rather than an empty
  // grey box -- a rider can still read the route.
  if (allPoints.length === 0) {
    const stops = routePath.slice(0, 12);
    return (
      <div className="route-map" aria-label="Route visualization">
        <div className="route-track">
          {stops.map((stop, index) => (
            <div key={`${stop}-${index}`} className="route-stop">
              <span className={`route-dot${index === 0 || index === stops.length - 1 ? " highlighted" : ""}`} />
              <span className="route-stop-label">{stop}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const start = allPoints[0];
  const end = allPoints[allPoints.length - 1];

  // Where one leg ends and the next begins. The backend guarantees these are
  // the same physical place (a transfer whose two stops are more than a short
  // walk apart is rejected outright), so one marker is honest here.
  const interchanges = legLines.slice(0, -1).map((line, index) => ({
    point: line.points[line.points.length - 1],
    from: line.leg?.bus_number,
    to: legLines[index + 1].leg?.bus_number,
    stop: line.leg?.to_stop,
  }));

  // Expanded, the map fills its portal wrapper; collapsed, it is a fixed-height
  // panel in the page. Both are explicit boxes -- the map's own height:100%
  // needs a parent with a definite height to resolve against.
  const containerStyle: React.CSSProperties = expanded
    ? { position: "absolute", inset: 0, borderRadius: 12, overflow: "hidden" }
    : { position: "relative", height: collapsedHeight, width: "100%", borderRadius: 12, overflow: "hidden" };

  const mapPanel = (
    <div className="route-map-container" style={containerStyle}>
      <button
        onClick={onToggleExpand}
        title={expanded ? "Exit full screen" : "Expand map"}
        aria-label={expanded ? "Exit full screen map" : "Expand map to full screen"}
        style={{
          position: "absolute", top: 10, right: 10, zIndex: 1000,
          background: "var(--surface-strong)", border: "1px solid var(--line-strong)",
          borderRadius: 8, padding: 8, cursor: "pointer", color: "var(--text)",
          display: "flex", alignItems: "center",
        }}
      >
        {expanded ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
      </button>

      <MapContainer
        center={start}
        zoom={12}
        style={{ height: "100%", width: "100%", background: "var(--surface)" }}
        zoomControl
        scrollWheelZoom={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
        />

        {legLines.map((line, index) => (
          <Polyline key={index} positions={line.points} color={line.colour} weight={5} opacity={0.85} />
        ))}

        <Marker position={start} icon={dotIcon("#10b981", "Boarding stop")}>
          <Popup>
            <strong>Board here</strong>
            {legLines[0].leg?.bus_number ? <> — bus {legLines[0].leg.bus_number}</> : null}
          </Popup>
        </Marker>

        {interchanges.map((change, index) => (
          <Marker key={index} position={change.point} icon={dotIcon("#f59e0b", "Change buses", 18)}>
            <Popup>
              <strong>Change here</strong>
              {change.stop ? <> — {change.stop}</> : null}
              {change.from && change.to ? <><br />{change.from} → {change.to}</> : null}
            </Popup>
          </Marker>
        ))}

        <Marker position={end} icon={dotIcon("#ef4444", "Destination stop")}>
          <Popup><strong>Get off here</strong></Popup>
        </Marker>

        <MapBehaviour expanded={expanded} bounds={allPoints} />
      </MapContainer>

      {legLines.length > 1 && (
        <div style={{
          position: "absolute", bottom: 10, left: 10, zIndex: 1000,
          background: "var(--surface-strong)", border: "1px solid var(--line-strong)",
          borderRadius: 8, padding: "6px 10px", display: "flex", gap: 12, flexWrap: "wrap",
          fontSize: "0.72rem", fontWeight: 600,
        }}>
          {legLines.map((line, index) => (
            <span key={index} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ width: 12, height: 3, background: line.colour, borderRadius: 2 }} />
              {line.leg?.bus_number || "Route"}
            </span>
          ))}
        </div>
      )}
    </div>
  );

  if (!expanded) return mapPanel;

  // Rendered into document.body, NOT in place.
  //
  // "position: fixed" is only relative to the viewport when no ancestor
  // establishes a containing block -- and this map lives inside .bento-card,
  // which sets `backdrop-filter: blur(16px)`. A backdrop-filter (like a
  // transform, and like the framer-motion wrapper further up this page) makes
  // that element the containing block for fixed descendants. So "full screen"
  // resolved to "40px inside the card", which is why expanding produced a
  // letterbox strip instead of a full-screen map. No amount of styling fixes
  // that from inside the card; the node has to leave it.
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Route map, full screen"
      onClick={onToggleExpand}
      style={{
        position: "fixed", inset: 0, zIndex: 9998,
        background: "rgba(0,0,0,0.8)", backdropFilter: "blur(5px)",
      }}
    >
      <div
        // Clicking the backdrop closes; clicking the map must not.
        onClick={(event) => event.stopPropagation()}
        style={{ position: "absolute", top: 40, right: 40, bottom: 40, left: 40 }}
      >
        {mapPanel}
      </div>
    </div>,
    document.body,
  );
}
