export type RouteCoordinate = {
  stop: string;
  lat: number | null;
  lon: number | null;
};

export type MetroStation = {
  station_code: string;
  station_name: string;
  line: string;
  sequence: number;
  is_interchange: boolean;
  latitude: number;
  longitude: number;
  line_color: string;
  distance_km?: number;
  distance_meters?: number;
  walking_minutes?: number;
  auto_minutes?: number;
  // How to actually get there when it is too far to walk. Null when walking
  // is the sensible answer, or when no bus route reaches the station.
  bus_connection?: {
    bus_chain: string;
    transfers: number;
    board_stop: string;
    alight_stop: string;
    distance_km?: number | null;
    duration_minutes?: number | null;
    total_stops?: number | null;
    final_walk_km: number;
    final_walk_minutes: number;
  } | null;
};

export type MetroInterchange = {
  has_metro_connection: boolean;
  station_name: string;
  lines: string[];
  is_interchange: boolean;
  interchange_stop: string;
};

export type RoutePrediction = {
  bus_number: string;
  confidence: number;
  relevance_score: number;
  route_id: string;
  direction_id: number;
  route_name: string;
  source: string;
  destination: string;
  matched_current_stop: string;
  matched_destination: string;
  stop_match_score: number;
  destination_match_score: number;
  passes_in_requested_order: boolean;
  trip_count: number;
  first_trips: string[];
  route_path: string[];
  total_stops: number;
  stop_span: number;
  distance_km: number;
  duration_minutes: number | null;
  distance_source: string;
  distance_complete: boolean;
  route_coordinates?: RouteCoordinate[];
  destination_nearest_metro?: MetroStation | null;
  destination_nearest_metro_list?: MetroStation[];
  // Present on every result (0 for a direct route); bus_number above is
  // always the bus to board first, so a transfer route also carries the
  // full chain and per-leg detail here -- see predictor.py's predict().
  transfers?: number;
  bus_chain?: string;
  transfer_stops?: string[];
  summary?: string;
  legs?: TransferLeg[];
  // Real signal for whether this route passes a known metro interchange;
  // null when it doesn't. See predictor.py's _detect_metro_interchange.
  metro_interchange?: MetroInterchange | null;
  current_stop_id?: string | null;
  destination_stop_id?: string | null;
};

export type TransferLeg = {
  bus_number: string;
  route_id: string;
  direction_id: number;
  route_name: string;
  source: string;
  destination: string;
  from_stop: string;
  to_stop: string;
  stop_count: number;
  trip_count: number;
  first_trips: string[];
  route_path: string[];
  distance_km: number;
  duration_minutes: number | null;
  distance_source: string;
  route_coordinates?: RouteCoordinate[];
};

export type TransferSuggestion = {
  confidence: number;
  transfers: number;
  total_stops: number;
  total_distance_km?: number | null;
  bus_chain: string;
  transfer_stops: string[];
  summary: string;
  legs: TransferLeg[];
  // Riding time plus a flat allowance per change; see
  // TRANSFER_PENALTY_MINUTES in predictor.py.
  duration_minutes?: number | null;
};

export type TransferStep = {
  from_stop: string;
  to_stop: string;
  options: TransferLeg[];
};

export type ServiceAlert = {
  id: string;
  title: string;
  description: string;
  severity: "info" | "moderate" | "severe";
  affected_routes: string[];
  affected_stops: string[];
  status: "active" | "resolved";
  created_at: string;
};

export type PredictionResponse = {
  query: {
    current_stop: string;
    destination: string;
  };
  best_match: RoutePrediction | null;
  alternatives: TransferSuggestion[];
  // Two readings of the same candidate set. They genuinely disagree: the
  // journey with fewest changes is often the longer ride, and the shortest
  // ride often needs an extra bus. `least_distance` may contain 2-transfer
  // journeys the fewest-changes view will never show.
  views?: {
    fewest_transfers: TransferSuggestion[];
    least_distance: TransferSuggestion[];
  };
  destination_nearest_metro?: MetroStation | null;
  destination_nearest_metro_list?: MetroStation[];
  // Real, moderated disruption alerts affecting this journey's routes or
  // stops (see alerts_service.py) -- always present, empty array means
  // no known disruptions rather than data being unavailable.
  active_alerts?: ServiceAlert[];
  message?: string;
  model: {
    name: string;
    trained_at: number;
    metrics: Record<string, number>;
  };
};

export type MetricsResponse = {
  selected_model: string;
  selection_reason: string;
  selected_model_metrics: Record<string, number>;
  candidate_models: Record<string, Record<string, number>>;
  cross_validation: Record<string, number>;
  training_seconds: number;
  dataset_profile: {
    rows: number;
    unique_bus_numbers: number;
    unique_stops: number;
    avg_stops_per_route: number;
    max_stops_per_route: number;
  };
  stop_pair_index?: {
    ordered_pairs: number;
    route_segments: number;
  };
  distance_provider?: {
    name: string;
    enabled: boolean;
    mode: string;
    cache_entries: number;
    coordinate_stops?: number;
  };
};

export type AutocompleteItem = {
  value: string;
  score: number;
};