import { Crosshair, RadioTower, ShieldCheck } from "lucide-react";

export function LiveOpsPanel() {
  return (
    <section className="dashboard-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Operations</p>
          <h2 className="panel-title">Live readiness</h2>
        </div>
      </div>
      <div className="ops-grid">
        <div>
          <RadioTower size={20} />
          <strong>Tracking adapter</strong>
          <span>Simulated demo engine (not GTFS-RT connected)</span>
        </div>
        <div>
          <Crosshair size={20} />
          <strong>Nearby stops</strong>
          <span>Browser geolocation ready</span>
        </div>
        <div>
          <ShieldCheck size={20} />
          <strong>API guardrails</strong>
          <span>Validation and rate limits</span>
        </div>
      </div>
    </section>
  );
}