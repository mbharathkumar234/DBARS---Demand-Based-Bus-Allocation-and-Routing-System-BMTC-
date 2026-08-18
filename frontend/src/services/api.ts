import type { AutocompleteItem, MetricsResponse, PredictionResponse } from "../types/api";
import { apiFetch } from "../lib/apiClient";

export type RoutePlan = {
  result: PredictionResponse;
  currentStop: string;
  destination: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Attach the session token when there is one. Without this, every call made
  // through this module was anonymous — which made the metrics dashboard's
  // "Retrain model" button (POST /train {force:true}, admin/depot_manager only)
  // fail with 401 every single time it was pressed.
  const token = localStorage.getItem("bmtc-token");
  const response = await apiFetch(path, {
    // `...init` must come FIRST: spreading it after `headers` would let an
    // init that carries its own headers replace the merged object wholesale
    // and silently drop both Content-Type and Authorization.
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function hasRoute(response: PredictionResponse) {
  return Boolean(response.best_match || response.alternatives?.length);
}

async function predict(current_stop: string, destination: string, limit = 50) {
  return request<PredictionResponse>("/predict", {
    method: "POST",
    body: JSON.stringify({ current_stop, destination, limit })
  });
}

async function autocomplete(q: string, kind: "stop" | "destination" = "stop") {
  const params = new URLSearchParams({ q, kind, limit: "10" });
  return request<{ items: AutocompleteItem[] }>(`/autocomplete?${params.toString()}`);
}

async function stopCandidates(value: string) {
  const seen = new Set<string>();
  const candidates = [value.trim()];
  const response = await autocomplete(value, "stop");
  for (const item of response.items) {
    if (item.score >= 0.72) {
      candidates.push(item.value);
    }
  }
  return candidates
    .filter((candidate) => {
      const key = candidate.toLowerCase();
      if (!candidate || seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .slice(0, 6);
}

async function planRoute(currentStop: string, destination: string, limit = 50): Promise<RoutePlan> {
  const initialCurrent = currentStop.trim();
  const initialDestination = destination.trim();
  const initial = await predict(initialCurrent, initialDestination, limit);
  let best: RoutePlan = {
    result: initial,
    currentStop: initial.query.current_stop,
    destination: initial.query.destination
  };
  if (hasRoute(initial)) {
    return best;
  }

  const [currentCandidates, destinationCandidates] = await Promise.all([
    stopCandidates(initialCurrent),
    stopCandidates(initialDestination)
  ]);

  const topCurrent = currentCandidates.slice(0, 2);
  const topDest = destinationCandidates.slice(0, 2);
  const candidatePairs: [string, string][] = [];

  for (const current of topCurrent) {
    for (const dest of topDest) {
      if (current === initialCurrent && dest === initialDestination) {
        continue;
      }
      candidatePairs.push([current, dest]);
    }
  }

  const candidateResults = await Promise.allSettled(
    candidatePairs.map(([c, d]) => predict(c, d, limit))
  );

  for (const res of candidateResults) {
    if (res.status === "fulfilled") {
      const response = res.value;
      const candidatePlan = {
        result: response,
        currentStop: response.query.current_stop,
        destination: response.query.destination
      };
      if (response.best_match) {
        return candidatePlan;
      }
      if (!hasRoute(best.result) && hasRoute(response)) {
        best = candidatePlan;
      }
    }
  }
  return best;
}

export const api = {
  predict(current_stop: string, destination: string, limit = 50) {
    return predict(current_stop, destination, limit);
  },
  autocomplete(q: string, kind: "stop" | "destination" = "stop") {
    return autocomplete(q, kind);
  },
  async resolveStop(value: string) {
    const response = await autocomplete(value, "stop");
    const best = response.items[0];
    return best && best.score >= 0.72 ? best.value : value;
  },
  planRoute(currentStop: string, destination: string, limit = 50) {
    return planRoute(currentStop, destination, limit);
  },
  metrics() {
    return request<MetricsResponse>("/metrics");
  },
  train(force = true) {
    return request<MetricsResponse>("/train", {
      method: "POST",
      body: JSON.stringify({ force })
    });
  },
  health() {
    return request<{ status: string; model_ready: boolean; dataset_rows: number; version: string }>("/health");
  },
  getMetroStations() {
    return request<{ status: string; total_stations: number; lines: string[]; stations: any[]; grouped_by_line: Record<string, any[]> }>("/metro/stations");
  },
  getNearestMetro(stopName?: string, lat?: number, lon?: number, limit = 3) {
    const params = new URLSearchParams();
    if (stopName) params.set("stop_name", stopName);
    if (lat !== undefined) params.set("lat", String(lat));
    if (lon !== undefined) params.set("lon", String(lon));
    params.set("limit", String(limit));
    return request<{ status: string; query_stop?: string; count: number; nearest_metro_stations: any[] }>(`/metro/nearest?${params.toString()}`);
  }
};
