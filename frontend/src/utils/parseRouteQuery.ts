/**
 * Split a spoken or typed phrase into an origin and a destination.
 *
 * This deliberately mirrors `_QUERY_PATTERN` in
 * backend/app/services/sms_service.py, which already solved this exact problem
 * for the SMS channel — including a trap worth keeping: a bare "-" is NOT a
 * separator, because real stop names in this dataset contain hyphens
 * ("CS-Kempegowda Bus Station"), and splitting on the first one would produce
 * "CS" and "Kempegowda Bus Station to Whitefield".
 *
 * The version this replaces (in SearchPanel) split on /\s+to\s+/ alone, so it
 * handled neither "->" nor a comma, and mangled hyphenated names.
 *
 * Keep the two in sync: if the SMS pattern gains a separator, add it here too.
 */
const QUERY_PATTERN = /^\s*(?:from\s+)?(.+?)\s*(?:\bto\b|->|,)\s*(.+?)\s*$/i;

export type RouteQuery = { origin: string; destination: string };

export function parseRouteQuery(text: string): RouteQuery | null {
  if (!text || !text.trim()) return null;
  const match = QUERY_PATTERN.exec(text.trim());
  if (!match) return null;
  const origin = match[1]?.trim() ?? "";
  const destination = match[2]?.trim() ?? "";
  if (!origin || !destination) return null;
  return { origin, destination };
}
