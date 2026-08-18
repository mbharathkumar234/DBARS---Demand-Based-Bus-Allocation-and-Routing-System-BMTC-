/**
 * Offline queue for onboard ticket sales.
 *
 * Offline is the DEFAULT operating mode here, not a fallback. Buses lose
 * signal constantly and a conductor cannot stop selling tickets while the
 * network decides whether it exists, so every sale is written locally first
 * and pushed when a connection is available.
 *
 * Two rules make that safe, and both live on the server side of the contract:
 *
 *   1. Every sale carries a client-generated UUID. The server dedupes on
 *      (waybill_id, client_ticket_uuid) with a unique index, so replaying the
 *      queue any number of times cannot count a sale twice.
 *
 *   2. The queue is cleared per item, only for what the server acknowledged.
 *      Clearing on a partial success is exactly how offline sales get lost,
 *      and a lost sale is indistinguishable afterwards from one never made.
 *
 * localStorage rather than IndexedDB: the payload is a few hundred small JSON
 * objects per shift at most, it is synchronous (so a sale cannot be lost to an
 * unawaited promise when the app is killed), and it survives a WebView restart
 * on the low-end Android devices this runs on.
 */

const QUEUE_KEY = "dbars-conductor-ticket-queue";

export type PassengerLine = {
  passenger_type: "adult" | "child" | "student" | "senior" | "shakti";
  count: number;
};

export type QueuedTicket = {
  waybill_id: string;
  client_ticket_uuid: string;
  from_stop: string;
  to_stop: string;
  passengers: PassengerLine[];
  payment_mode: "cash" | "upi" | "pass" | "free";
  is_ac: boolean;
  issued_at: string;
};

function readQueue(): QueuedTicket[] {
  try {
    const raw = localStorage.getItem(QUEUE_KEY);
    return raw ? (JSON.parse(raw) as QueuedTicket[]) : [];
  } catch {
    // A corrupt queue must not brick the scanner mid-shift. Losing unsynced
    // sales is bad; a conductor who cannot issue any ticket at all is worse.
    return [];
  }
}

function writeQueue(tickets: QueuedTicket[]): void {
  localStorage.setItem(QUEUE_KEY, JSON.stringify(tickets));
}

export function newTicketId(): string {
  // crypto.randomUUID is unavailable on older Android WebViews, which is
  // exactly the hardware this runs on.
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function enqueue(ticket: QueuedTicket): void {
  writeQueue([...readQueue(), ticket]);
}

export function pending(): QueuedTicket[] {
  return readQueue();
}

export function pendingCount(): number {
  return readQueue().length;
}

export type SyncOutcome = {
  accepted: number;
  duplicates: number;
  rejected: { client_ticket_uuid: string; reason: string }[];
  remaining: number;
};

/**
 * Push the queue and remove only what the server confirmed it holds.
 *
 * Duplicates count as settled: the server already has them, which is the
 * offline queue working correctly rather than an error. Rejections are also
 * removed but returned to the caller, because a sale the server will never
 * accept (a closed waybill, an unrecognised stop) will not become acceptable
 * by being retried forever -- it needs a person to see it.
 */
export async function flush(
  post: (tickets: QueuedTicket[]) => Promise<Response>,
): Promise<SyncOutcome> {
  const queue = readQueue();
  if (queue.length === 0) {
    return { accepted: 0, duplicates: 0, rejected: [], remaining: 0 };
  }

  const response = await post(queue);
  if (!response.ok) {
    // Leave the queue untouched: an unacknowledged batch has not been
    // recorded, and dropping it here would lose real money.
    throw new Error(`Sync failed (HTTP ${response.status}). Sales are still queued.`);
  }

  const result = await response.json();
  const settled = new Set<string>([
    ...(result.accepted || []).map((item: any) => item.client_ticket_uuid),
    ...(result.duplicates || []).map((item: any) => item.client_ticket_uuid),
    ...(result.rejected || []).map((item: any) => item.client_ticket_uuid),
  ]);

  const remaining = queue.filter((ticket) => !settled.has(ticket.client_ticket_uuid));
  writeQueue(remaining);

  return {
    accepted: result.counts?.accepted ?? 0,
    duplicates: result.counts?.duplicates ?? 0,
    rejected: result.rejected || [],
    remaining: remaining.length,
  };
}

export function clearQueue(): void {
  localStorage.removeItem(QUEUE_KEY);
}
