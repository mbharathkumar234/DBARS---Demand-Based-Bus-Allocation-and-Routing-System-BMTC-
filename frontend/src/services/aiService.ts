import { apiFetch } from "../lib/apiClient";

export type RetrievalMode =
  | "auto"
  | "travel"
  | "operations"
  | "code"
  | "documentation"
  | "routing"
  | "hybrid";

export type GroundingConfidence = "CONFIRMED" | "INFERRED" | "UNKNOWN";

export interface Citation {
  source_type: "code" | "documentation" | "dbars_tool" | "system" | string;
  title: string;
  path?: string | null;
  symbol?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  section?: string | null;
  snippet?: string | null;
}

export interface ToolExecutionRecord {
  tool_name: string;
  arguments: Record<string, any>;
  output: any;
  execution_time_ms: number;
  status: "success" | "error" | string;
}

export interface AIChatRequest {
  query: string;
  session_id?: string | null;
  user_id?: string | null;
  retrieval_mode?: RetrievalMode;
  include_sources?: boolean;
}

export interface AIChatResponse {
  answer: string;
  grounding: GroundingConfidence;
  sources: Citation[];
  tools_called: ToolExecutionRecord[];
  session_id: string;
  model_used: string;
  latency_ms: number;
}

export interface AIHealthResponse {
  status: string;
  version: string;
  enabled: boolean;
  provider: string;
  model: string;
  code_index_ready: boolean;
  doc_index_ready: boolean;
  dbars_tools_registered: number;
}

export interface SessionClearResponse {
  session_id: string;
  cleared: boolean;
  message: string;
}

export interface SessionHistoryResponse {
  session_id: string;
  user_id?: string | null;
  turns: Array<{ role: string; content: string }>;
  journey_context: Record<string, any>;
}

/**
 * Submits a natural language query to the DBARS AI Assistant.
 */
function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = localStorage.getItem("bmtc-token");
  return { ...extra, ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

export async function sendAIChat(request: AIChatRequest): Promise<AIChatResponse> {
  const response = await apiFetch("/ai/chat", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorPayload = await response.json().catch(() => ({}));
    throw new Error(errorPayload.detail || `AI chat failed with status ${response.status}`);
  }

  return response.json() as Promise<AIChatResponse>;
}

/**
 * Checks readiness of the AI layer (code index, doc index, registered tools).
 */
export async function fetchAIHealth(): Promise<AIHealthResponse> {
  const response = await apiFetch("/ai/health", {
    method: "GET",
  });

  if (!response.ok) {
    throw new Error(`AI health check failed with status ${response.status}`);
  }

  return response.json() as Promise<AIHealthResponse>;
}

/**
 * Explicitly clears conversational memory and active journey context for a session.
 */
export async function clearAISession(sessionId: string): Promise<SessionClearResponse> {
  const response = await apiFetch("/ai/session/clear", {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ session_id: sessionId }),
  });

  if (!response.ok) {
    throw new Error(`Failed to clear session with status ${response.status}`);
  }

  return response.json() as Promise<SessionClearResponse>;
}

/**
 * Retrieves sanitized turn history and active journey context for a session.
 */
export async function fetchAISessionHistory(sessionId: string): Promise<SessionHistoryResponse> {
  const url = `/ai/session/${encodeURIComponent(sessionId)}/history`;
  const response = await apiFetch(url, { method: "GET", headers: authHeaders() });

  if (!response.ok) {
    throw new Error(`Failed to fetch history with status ${response.status}`);
  }

  return response.json() as Promise<SessionHistoryResponse>;
}
