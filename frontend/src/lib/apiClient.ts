// Single source of truth for the backend URL. Every service/page/context
// should import from here instead of reading import.meta.env.VITE_API_URL
// itself — that's how the same dev IP ended up baked into 9 separate spots
// in the production bundle.
export const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * fetch() wrapper for calls to our own backend. Prefixes API_BASE_URL and,
 * critically, catches network-layer failures (DNS, connection refused,
 * offline, blocked cleartext, etc.) and rethrows them with a message a
 * user can actually act on — instead of the raw "TypeError: Failed to
 * fetch" that the browser/WebView throws for all of those cases.
 *
 * Existing `catch (err) { toast.error(err.message || "fallback") }` call
 * sites don't need to change: they already prefer err.message when it's
 * present, so fixing the message here fixes every toast in the app.
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch (err) {
    if (err instanceof TypeError) {
      throw new Error("Can't reach the server. Check your connection and try again.");
    }
    throw err;
  }
  return response;
}
