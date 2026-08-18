import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, CloudOff, CloudUpload, LogIn, LogOut, Ticket, Wifi,
} from "lucide-react";
import toast from "react-hot-toast";
import { apiFetch } from "../lib/apiClient";
import { useAuth } from "../contexts/AuthContext";
import {
  enqueue, flush, newTicketId, pendingCount, type PassengerLine, type QueuedTicket,
} from "../lib/offlineQueue";

/**
 * The conductor's working day: sign on, issue tickets, sign off, remit cash.
 *
 * This is the workflow a conductor actually performs, and the one part of
 * DBARS that touches money. Two things drive the design:
 *
 *   Offline is the default. Every sale goes into the local queue first and is
 *   pushed opportunistically. The pending count is always visible, because a
 *   conductor must be able to see how much of their shift is unsynced.
 *
 *   Nothing is priced on the device. The server computes the fare from the
 *   published stage table and returns it; a client-side fare would drift from
 *   the commuter e-ticket's and give two answers for the same journey.
 */

const PASSENGER_TYPES: { value: PassengerLine["passenger_type"]; label: string }[] = [
  { value: "adult", label: "Adult" },
  { value: "child", label: "Child" },
  { value: "student", label: "Student" },
  { value: "senior", label: "Senior" },
  { value: "shakti", label: "Shakti (free)" },
];

export default function ConductorDuty() {
  const { token, user } = useAuth();
  const navigate = useNavigate();

  const [waybill, setWaybill] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [queued, setQueued] = useState(pendingCount());
  const [online, setOnline] = useState(navigator.onLine);
  const [syncing, setSyncing] = useState(false);

  const [routeNumber, setRouteNumber] = useState("");
  const [busReg, setBusReg] = useState("");
  const [depot, setDepot] = useState("");
  const [openingKm, setOpeningKm] = useState("");

  const [fromStop, setFromStop] = useState("");
  const [toStop, setToStop] = useState("");
  const [passengerType, setPassengerType] = useState<PassengerLine["passenger_type"]>("adult");
  const [count, setCount] = useState(1);
  const [paymentMode, setPaymentMode] = useState<QueuedTicket["payment_mode"]>("cash");

  const [closingKm, setClosingKm] = useState("");
  const [declaredCash, setDeclaredCash] = useState("");

  const authHeaders = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  // Recover state on launch: the app is routinely killed mid-shift on the
  // low-end devices this runs on, and the waybill lives on the server.
  useEffect(() => {
    if (!token) return;
    apiFetch(`/conductor/waybill`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => (r.ok ? r.json() : null))
      .then((data) => setWaybill(data?.waybill ?? null))
      .catch(() => { })
      .finally(() => setLoading(false));
  }, [token]);

  const syncNow = useCallback(async () => {
    if (pendingCount() === 0) return;
    setSyncing(true);
    try {
      const outcome = await flush((tickets) =>
        apiFetch(`/conductor/tickets/sync`, {
          method: "POST", headers: authHeaders, body: JSON.stringify({ tickets }),
        }),
      );
      setQueued(outcome.remaining);
      if (outcome.accepted) toast.success(`Synced ${outcome.accepted} ticket(s).`);
      // A rejection will never become acceptable by being retried, so it is
      // surfaced to the conductor rather than silently dropped.
      outcome.rejected.forEach((item) => toast.error(`Ticket rejected: ${item.reason}`, { duration: 8000 }));
    } catch (err: any) {
      toast.error(err.message || "Could not sync. Sales are still queued.");
    } finally {
      setSyncing(false);
    }
  }, [token]);

  useEffect(() => {
    if (online && queued > 0 && !syncing) void syncNow();
  }, [online, queued, syncNow, syncing]);

  const signOn = async () => {
    try {
      const response = await apiFetch(`/conductor/sign-on`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({
          route_number: routeNumber.trim(), bus_reg: busReg.trim(),
          depot: depot.trim(), opening_km: Number(openingKm) || 0,
        }),
      });
      const data = await response.json();
      if (!response.ok) { toast.error(String(data.detail)); return; }
      setWaybill(data.waybill);
      toast.success(`Signed on — waybill ${data.waybill.waybill_id}`);
    } catch (err: any) {
      toast.error(err.message || "Could not sign on.");
    }
  };

  const issueTicket = async () => {
    if (!waybill) return;
    if (!fromStop.trim() || !toStop.trim()) { toast.error("Enter both stops."); return; }

    const ticket: QueuedTicket = {
      waybill_id: waybill.waybill_id,
      client_ticket_uuid: newTicketId(),
      from_stop: fromStop.trim(),
      to_stop: toStop.trim(),
      passengers: [{ passenger_type: passengerType, count }],
      // Shakti travel is free at the point of use, so nothing changes hands.
      payment_mode: passengerType === "shakti" ? "free" : paymentMode,
      is_ac: false,
      issued_at: new Date().toISOString(),
    };

    // Queue first, always. If the push succeeds the queue drains immediately;
    // if it does not, the sale is already safely recorded on the device.
    enqueue(ticket);
    setQueued(pendingCount());
    toast.success(passengerType === "shakti" ? "Shakti boarding recorded (free)" : "Ticket issued");
    if (online) await syncNow();
  };

  const signOff = async () => {
    if (!waybill) return;
    if (pendingCount() > 0) {
      // Signing off closes the waybill, and the server refuses tickets against
      // a closed one. Draining first is what stops a shift's last sales from
      // being rejected on arrival.
      toast.error(`${pendingCount()} ticket(s) still unsynced. Syncing before sign-off…`);
      await syncNow();
      if (pendingCount() > 0) return;
    }
    try {
      const response = await apiFetch(`/conductor/sign-off`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({
          waybill_id: waybill.waybill_id,
          closing_km: Number(closingKm) || 0,
          declared_cash: Number(declaredCash) || 0,
        }),
      });
      const data = await response.json();
      if (!response.ok) { toast.error(String(data.detail)); return; }
      const reconciliation = data.waybill.reconciliation;
      setWaybill(null);
      toast.success(
        `Signed off. Expected ₹${reconciliation.expected_cash}, declared ₹${reconciliation.declared_cash}` +
        (reconciliation.variance ? ` (variance ₹${reconciliation.variance})` : ""),
        { duration: 9000 },
      );
    } catch (err: any) {
      toast.error(err.message || "Could not sign off.");
    }
  };

  if (loading) {
    return <div className="page-container"><p className="text-muted">Loading your duty…</p></div>;
  }

  return (
    <div className="page-container" style={{ maxWidth: 720, margin: "0 auto", padding: "1.5rem" }}>
      <button className="btn btn-ghost" onClick={() => navigate("/dashboard")} style={{ marginBottom: "1rem" }}>
        <ArrowLeft size={16} /> Back
      </button>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
        <h1 style={{ fontSize: "1.4rem", margin: 0 }}>Conductor duty</h1>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: "0.8rem" }}>
          {online ? <Wifi size={16} style={{ color: "#10b981" }} /> : <CloudOff size={16} style={{ color: "#f59e0b" }} />}
          <span className="text-muted">{online ? "Online" : "Offline"}</span>
          <span style={{
            padding: "2px 10px", borderRadius: 999, fontWeight: 700,
            background: queued ? "#f59e0b22" : "var(--surface-strong)",
            color: queued ? "#f59e0b" : "var(--text-3)",
          }}>
            {queued} unsynced
          </span>
          {queued > 0 && (
            <button className="btn btn-ghost" onClick={syncNow} disabled={syncing || !online}>
              <CloudUpload size={15} /> Sync
            </button>
          )}
        </div>
      </div>

      {user && (
        <p className="text-muted" style={{ fontSize: "0.8rem", marginTop: 0 }}>
          Signed in as {user.name} ({user.role})
        </p>
      )}

      {!waybill ? (
        <div className="bento-card" style={{ padding: "1.5rem" }}>
          <h3 style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 8 }}>
            <LogIn size={18} /> Sign on
          </h3>
          <div style={{ display: "grid", gap: "0.85rem" }}>
            <input className="input" placeholder="Route number (e.g. 500-D)" value={routeNumber} onChange={(e) => setRouteNumber(e.target.value)} />
            <input className="input" placeholder="Bus registration (e.g. KA01F1234)" value={busReg} onChange={(e) => setBusReg(e.target.value)} />
            <input className="input" placeholder="Depot" value={depot} onChange={(e) => setDepot(e.target.value)} />
            <input className="input" type="number" placeholder="Opening odometer (km)" value={openingKm} onChange={(e) => setOpeningKm(e.target.value)} />
            <button className="btn btn-primary" onClick={signOn}>Sign on and open waybill</button>
          </div>
        </div>
      ) : (
        <>
          <div className="bento-card" style={{ padding: "1.25rem", marginBottom: "1.25rem" }}>
            <div style={{ fontSize: "0.78rem" }} className="text-muted">Waybill</div>
            <div style={{ fontWeight: 800, fontSize: "1.05rem" }}>{waybill.waybill_id}</div>
            <div className="text-muted" style={{ fontSize: "0.82rem", marginTop: 4 }}>
              Route {waybill.route_number} · Bus {waybill.bus_reg} · Opened {waybill.opening_km} km
            </div>
          </div>

          <div className="bento-card" style={{ padding: "1.5rem", marginBottom: "1.25rem" }}>
            <h3 style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 8 }}>
              <Ticket size={18} /> Issue ticket
            </h3>
            <div style={{ display: "grid", gap: "0.85rem" }}>
              <input className="input" placeholder="From stop" value={fromStop} onChange={(e) => setFromStop(e.target.value)} />
              <input className="input" placeholder="To stop" value={toStop} onChange={(e) => setToStop(e.target.value)} />
              <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
                <select className="input" value={passengerType} onChange={(e) => setPassengerType(e.target.value as any)}>
                  {PASSENGER_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                </select>
                <input className="input" type="number" min={1} max={60} value={count}
                  onChange={(e) => setCount(Math.max(1, Number(e.target.value)))} style={{ width: 90 }} />
                <select className="input" value={paymentMode} disabled={passengerType === "shakti"}
                  onChange={(e) => setPaymentMode(e.target.value as any)}>
                  <option value="cash">Cash</option>
                  <option value="upi">UPI</option>
                  <option value="pass">Pass</option>
                </select>
              </div>
              {passengerType === "shakti" && (
                <p className="text-muted" style={{ fontSize: "0.78rem", margin: 0 }}>
                  Free to the passenger. The fare value is still recorded — that is the amount
                  BMTC claims back from the state, so the boarding must be issued, not skipped.
                </p>
              )}
              <button className="btn btn-primary" onClick={issueTicket}>Issue</button>
            </div>
          </div>

          <div className="bento-card" style={{ padding: "1.5rem" }}>
            <h3 style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 8 }}>
              <LogOut size={18} /> Sign off
            </h3>
            <div style={{ display: "grid", gap: "0.85rem" }}>
              <input className="input" type="number" placeholder="Closing odometer (km)" value={closingKm} onChange={(e) => setClosingKm(e.target.value)} />
              <input className="input" type="number" placeholder="Cash on hand (₹)" value={declaredCash} onChange={(e) => setDeclaredCash(e.target.value)} />
              <p className="text-muted" style={{ fontSize: "0.78rem", margin: 0 }}>
                Your declared cash is compared against the total of the cash tickets issued on this
                waybill. A difference is recorded and shown to the depot — it is never adjusted away.
              </p>
              <button className="btn btn-primary" onClick={signOff}>Sign off and remit</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
