import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AutocompleteInput } from "../components/AutocompleteInput";
import { ticketApi, TicketResponse } from "../services/ticketApi";
import { QRCodeSVG } from "qrcode.react";
import { Ticket, CreditCard, Clock, MapPin, CheckCircle, AlertCircle, ArrowLeft } from "lucide-react";
import toast from "react-hot-toast";
import { motion } from "framer-motion";
import { useLanguage } from "../contexts/LanguageContext";
import { useAuth } from "../contexts/AuthContext";

export default function Tickets() {
  const navigate = useNavigate();
  const { t } = useLanguage();
  const { user } = useAuth();
  const [source, setSource] = useState("");
  const [destination, setDestination] = useState("");
  const [fare, setFare] = useState<number | null>(null);
  const [activeTicket, setActiveTicket] = useState<TicketResponse | null>(null);
  const [loadingFare, setLoadingFare] = useState(false);
  const [loadingPurchase, setLoadingPurchase] = useState(false);
  const [view, setView] = useState<"buy" | "active">("active");

  useEffect(() => {
    fetchActiveTicket();
  }, []);

  const fetchActiveTicket = async () => {
    try {
      const ticket = await ticketApi.getActiveTicket();
      if (ticket) {
        setActiveTicket(ticket);
        setView("active");
      } else {
        setView("buy");
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    if (source && destination && source !== destination) {
      const getFare = async () => {
        setLoadingFare(true);
        try {
          const res = await ticketApi.getFare(source, destination);
          setFare(res.fare);
        } catch (e) {
          setFare(null);
        }
        setLoadingFare(false);
      };
      getFare();
    } else {
      setFare(null);
    }
  }, [source, destination]);

  const handlePurchase = async () => {
    if (!fare || !source || !destination) return;
    setLoadingPurchase(true);

    // Simulate a payment delay
    await new Promise(r => setTimeout(r, 1500));

    try {
      const ticket = await ticketApi.purchaseTicket({
        source_stop: source,
        destination_stop: destination,
        fare_amount: fare
      });
      toast.success("Ticket Purchased Successfully!");
      setActiveTicket(ticket);
      setView("active");
    } catch (err: any) {
      toast.error(err.message || "Purchase failed");
    } finally {
      setLoadingPurchase(false);
    }
  };

  return (
    <div className="container mx-auto max-w-md p-4 pt-6">
      {/* Back button + title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem' }}>
        <button
          type="button"
          onClick={() => navigate(-1)}
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface-strong)', border: '1px solid var(--line-strong)', borderRadius: '50%', width: '36px', height: '36px', cursor: 'pointer', color: 'var(--text)', flexShrink: 0, transition: 'background 0.15s' }}
          onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-sunken)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'var(--surface-strong)')}
          title="Go Back"
        >
          <ArrowLeft size={17} />
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Ticket size={20} style={{ color: 'var(--brand)' }} />
          <span style={{ fontWeight: 700, fontSize: '1.1rem' }}>My Tickets</span>
        </div>
      </div>
      <div className="flex bg-surface-2 rounded-xl p-1 mb-6">
        <button
          onClick={() => setView("buy")}
          className={`flex-1 py-2 text-sm font-medium rounded-lg flex items-center justify-center gap-2 transition-colors ${view === 'buy' ? 'bg-primary text-white shadow' : 'text-text-2 hover:text-text-1'}`}
        >
          <CreditCard className="w-4 h-4" />
          Buy Ticket
        </button>
        <button
          onClick={() => setView("active")}
          className={`flex-1 py-2 text-sm font-medium rounded-lg flex items-center justify-center gap-2 transition-colors ${view === 'active' ? 'bg-primary text-white shadow' : 'text-text-2 hover:text-text-1'}`}
        >
          <Ticket className="w-4 h-4" />
          Active Ticket
        </button>
      </div>

      {view === "buy" && (
        <div className="bg-surface rounded-2xl p-6 border border-border shadow-sm">
          <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
            <Ticket className="w-6 h-6 text-primary" />
            Purchase Ticket
          </h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-text-2 mb-1">From</label>
              <AutocompleteInput
                kind="stop"
                placeholder="Source Stop"
                value={source}
                onChange={setSource} label={""}              />
            </div>

            <div>
              <label className="block text-sm font-medium text-text-2 mb-1">To</label>
              <AutocompleteInput
                kind="stop"
                placeholder="Destination Stop"
                value={destination}
                onChange={setDestination} label={""}              />
            </div>

            {loadingFare && (
              <div className="py-4 text-center text-text-2 animate-pulse text-sm">
                Calculating fare...
              </div>
            )}

            {!loadingFare && fare !== null && (
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-surface-2 rounded-xl p-4 mt-6"
              >
                {/* Told BEFORE the payment step, not after it. A passenger
                    entitled to free travel should never be shown a fare she is
                    about to be asked to pay and then surprised by a zero. */}
                {user?.shakti_eligible ? (
                  <div className="flex justify-between items-center mb-4">
                    <div>
                      <span className="text-text-2">Fare</span>
                      <p style={{ margin: "2px 0 0 0", fontSize: "0.72rem", color: "#10b981", fontWeight: 600 }}>
                        {t("tickets.shakti_badge")}
                      </p>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <span className="text-2xl font-bold" style={{ color: "#10b981" }}>₹0</span>
                      <p style={{ margin: 0, fontSize: "0.72rem", color: "var(--text-3)", textDecoration: "line-through" }}>
                        ₹{fare}
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="flex justify-between items-center mb-4">
                    <span className="text-text-2">Estimated Fare</span>
                    <span className="text-2xl font-bold text-primary">₹{fare}</span>
                  </div>
                )}

                <button
                  onClick={handlePurchase}
                  disabled={loadingPurchase}
                  className="w-full py-3 bg-primary hover:bg-primary-hover text-white rounded-lg font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50"
                >
                  {loadingPurchase ? (
                    <span className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></span>
                  ) : (
                    <>
                      <CheckCircle className="w-5 h-5" />
                      {user?.shakti_eligible ? "Get free Shakti ticket" : "Simulate Mock Payment"}
                    </>
                  )}
                </button>
                <p className="text-xs text-center text-text-3 mt-3">
                  {user?.shakti_eligible
                    ? "No payment is taken. The fare above is what BMTC claims back from the State."
                    : "This is a simulated payment for demo purposes."}
                </p>
              </motion.div>
            )}

            {!loadingFare && fare === null && source && destination && source !== destination && (
              <div className="py-4 text-center text-red-500 text-sm flex items-center justify-center gap-2">
                <AlertCircle className="w-4 h-4" />
                No direct fare found for this route.
              </div>
            )}
          </div>
        </div>
      )}

      {view === "active" && (
        <div>
          {activeTicket ? (
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="bg-surface border border-border shadow-md rounded-3xl overflow-hidden"
            >
              <div className="bg-primary text-white p-6 text-center">
                <h3 className="text-xl font-bold">BMTC E-Ticket</h3>
                <p className="opacity-90 text-sm mt-1">Confirmed Travel Intent</p>
              </div>

              <div className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <div className="flex-1">
                    <p className="text-xs text-text-3 uppercase tracking-wider font-semibold mb-1">Source</p>
                    <p className="font-semibold text-text-1 truncate">{activeTicket.source_stop}</p>
                  </div>
                  <div className="px-4 text-text-3">
                    <MapPin className="w-5 h-5" />
                  </div>
                  <div className="flex-1 text-right">
                    <p className="text-xs text-text-3 uppercase tracking-wider font-semibold mb-1">Destination</p>
                    <p className="font-semibold text-text-1 truncate">{activeTicket.destination_stop}</p>
                  </div>
                </div>

                <div className="flex flex-col items-center my-8 p-4 bg-white rounded-2xl mx-auto w-fit">
                  <QRCodeSVG value={activeTicket.qr_token} size={200} level="M" />
                  {activeTicket.short_code && (
                    <p
                      style={{
                        marginTop: '12px',
                        fontFamily: "'Courier New', Courier, monospace",
                        fontSize: '1.75rem',
                        fontWeight: 800,
                        letterSpacing: '0.35em',
                        color: '#1a1a2e',
                        textAlign: 'center',
                        userSelect: 'none',
                      }}
                    >
                      {activeTicket.short_code}
                    </p>
                  )}
                </div>

                {/* A Shakti ticket is issued identically -- same QR, same
                    six-character code -- so a conductor verifies it with the
                    same scan. Only the money differs, and both halves of that
                    are shown: nothing paid, and the value BMTC claims back. */}
                {activeTicket.is_zero_fare && (
                  <div style={{
                    margin: "0 0 1rem 0", padding: "0.85rem 1rem", borderRadius: 12,
                    background: "rgba(16,185,129,0.12)", border: "1px solid #10b98155",
                  }}>
                    <p style={{ margin: 0, fontWeight: 800, color: "#10b981", letterSpacing: "0.02em" }}>
                      {t("tickets.shakti_badge")}
                    </p>
                    {activeTicket.fare_value_inr != null && (
                      <p style={{ margin: "4px 0 0 0", fontSize: "0.78rem", color: "var(--text-3)" }}>
                        {t("tickets.shakti_value").replace("{v}", String(activeTicket.fare_value_inr))}
                      </p>
                    )}
                    {activeTicket.scheme_note && (
                      <p style={{ margin: "6px 0 0 0", fontSize: "0.72rem", color: "var(--text-3)", lineHeight: 1.45 }}>
                        {activeTicket.scheme_note}
                      </p>
                    )}
                  </div>
                )}

                <div className="grid grid-cols-2 gap-4 bg-surface-2 p-4 rounded-xl">
                  <div>
                    <p className="text-xs text-text-3 mb-1">{activeTicket.is_zero_fare ? "Fare" : "Fare Paid"}</p>
                    <p className="font-semibold text-primary">
                      {activeTicket.is_zero_fare ? "₹0" : `₹${activeTicket.fare_amount}`}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-text-3 mb-1">Valid Until</p>
                    <p className="font-semibold text-red-500 flex items-center justify-end gap-1">
                      <Clock className="w-4 h-4" />
                      {new Date(activeTicket.expiry_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </p>
                  </div>
                </div>

                {/* Live element to prevent screenshots */}
                <div className="mt-4 flex justify-center items-center gap-2 text-xs font-medium text-green-500">
                  <span className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
                  </span>
                  Live Ticket Active
                </div>
              </div>
            </motion.div>
          ) : (
            <div className="text-center py-16 bg-surface rounded-2xl border border-border">
              <Ticket className="w-16 h-16 text-text-3 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-text-1">No Active Tickets</h3>
              <p className="text-text-2 mt-2 mb-6">You don't have any valid tickets for travel right now.</p>
              <button
                onClick={() => setView("buy")}
                className="px-6 py-2 bg-primary hover:bg-primary-hover text-white rounded-lg transition-colors font-medium"
              >
                Buy a Ticket
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
