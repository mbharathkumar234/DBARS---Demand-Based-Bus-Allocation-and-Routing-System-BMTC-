import { useEffect, useState } from "react";
import { Activity, Database, GitBranch, RefreshCw } from "lucide-react";
import { api } from "../services/api";
import type { MetricsResponse } from "../types/api";

export function MetricsDashboard() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (force = false) => {
    setLoading(true);
    setError(null);
    try {
      const response = force ? await api.train(true) : await api.metrics();
      setMetrics(response);
    } catch (err) {
      // Previously there was no catch here at all, and the retrain button called
      // load(true) without one either — so a failed retrain (which was every
      // retrain, see api.ts) produced an unhandled promise rejection and no
      // visible feedback whatsoever. The spinner just stopped.
      setError(err instanceof Error ? err.message : "Could not load model metrics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(false).catch(() => undefined);
  }, []);

  if (!metrics) {
    return (
      <section className="dashboard-panel">
        {error ? `Could not load model metrics: ${error}` : "Model metrics are loading."}
      </section>
    );
  }

  const model = metrics.selected_model_metrics;
  const profile = metrics.dataset_profile;

  return (
    <section className="dashboard-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Model evaluation</p>
          <h2 className="panel-title">{metrics.selected_model}</h2>
        </div>
        <button type="button" className="icon-button" onClick={() => load(true)} title="Retrain model" aria-label="Retrain model" disabled={loading}>
          <RefreshCw size={18} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && <p className="small-copy" role="alert">Retrain failed: {error}</p>}

      <div className="metric-grid">
        <div className="metric-tile">
          <Activity size={19} />
          <span>Top 1</span>
          <strong>{Math.round((model.accuracy_top_1 ?? 0) * 100)}%</strong>
        </div>
        <div className="metric-tile">
          <GitBranch size={19} />
          <span>Top 5</span>
          <strong>{Math.round((model.accuracy_top_5 ?? 0) * 100)}%</strong>
        </div>
        <div className="metric-tile">
          <Database size={19} />
          <span>Routes</span>
          <strong>{profile.rows.toLocaleString()}</strong>
        </div>
        <div className="metric-tile">
          <Database size={19} />
          <span>Stops</span>
          <strong>{profile.unique_stops.toLocaleString()}</strong>
        </div>
        <div className="metric-tile">
          <GitBranch size={19} />
          <span>Stop pairs</span>
          <strong>{(metrics.stop_pair_index?.ordered_pairs ?? 0).toLocaleString()}</strong>
        </div>
        <div className="metric-tile">
          <Database size={19} />
          <span>Geo stops</span>
          <strong>{(metrics.distance_provider?.coordinate_stops ?? 0).toLocaleString()}</strong>
        </div>
      </div>

      <p className="small-copy">{metrics.selection_reason}</p>
    </section>
  );
}
