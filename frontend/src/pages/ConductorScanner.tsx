import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Html5QrcodeScanner } from "html5-qrcode";
import { ticketApi } from "../services/ticketApi";
import { ScanLine, CheckCircle, XCircle, ShieldCheck, WifiOff, Zap, ArrowLeft } from "lucide-react";
import toast from "react-hot-toast";
import { apiFetch } from "../lib/apiClient";
import { useAuth } from "../contexts/AuthContext";

/**
 * Read the `type` a signed token declares, without verifying it.
 *
 * Only used to decide which endpoint should verify the scan. The signature is
 * checked server-side against a different key per token type, so a token
 * claiming to be something it is not gets rejected there -- lying here buys an
 * attacker nothing but a failed verification against the wrong key.
 */
function declaredTokenType(token: string): string | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const padded = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(padded + "=".repeat((4 - (padded.length % 4)) % 4))).type ?? null;
  } catch {
    return null;
  }
}

export default function ConductorScanner() {
  const navigate = useNavigate();
  const { user, token: authToken } = useAuth();
  const [scanResult, setScanResult] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(true);
  const [offlineMode, setOfflineMode] = useState(true);
  const [scanCount, setScanCount] = useState(0);
  // The route this conductor is working, taken from their open waybill rather
  // than hardcoded, so a scan is attributed to the duty it happened on.
  const [activeRoute, setActiveRoute] = useState("");

  const playAudioBeep = (success: boolean) => {
    try {
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = success ? "sine" : "sawtooth";
      osc.frequency.setValueAtTime(success ? 880 : 320, ctx.currentTime);
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + (success ? 0.2 : 0.4));
    } catch (e) {
      // Audio context might be restricted
    }
  };

  const handleVerifyPass = async (scannedToken: string) => {
    setLoading(true);
    try {
      const resp = await apiFetch(`/conductor/verify-pass`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          // The QR code carries a signed pass token, not a bare id: the
          // signature is what makes the pass verifiable, and the server checks
          // it rather than inspecting the id's text as it once did.
          token: scannedToken,
          // The real conductor, from their session -- this was hardcoded to
          // "CND-402" and "500-D", so every scan in the system was attributed
          // to a conductor who does not exist.
          conductor_id: user?.id ?? null,
          route_id: activeRoute || null,
          offline_mode: offlineMode
        })
      });
      const data = await resp.json();
      setScanResult(data);
      setScanCount((prev) => prev + 1);
      const isSuccess = data.status === "VALID";
      playAudioBeep(isSuccess);
      if (isSuccess) {
        toast.success(
          data.demo_mode
            ? `DEMO — no signature checked`
            : `Verified: ${data.pass_type ?? "pass"}`
        );
      } else {
        toast.error(`Rejected: ${data.reason ?? data.detail ?? "invalid pass"}`);
      }
    } catch (err: any) {
      toast.error(err.message || "Verification error");
      setScanResult({ status: "INVALID", reason: "Could not reach the pass verifier." });
      playAudioBeep(false);
    } finally {
      setLoading(false);
      setScanning(false);
    }
  };

  // Attribute scans to the duty they happen on. Without this the route was a
  // hardcoded "500-D" on every scan in the system.
  useEffect(() => {
    if (!authToken) return;
    apiFetch(`/conductor/waybill`, { headers: { Authorization: `Bearer ${authToken}` } })
      .then(async (r) => (r.ok ? r.json() : null))
      .then((data) => setActiveRoute(data?.waybill?.route_number ?? ""))
      .catch(() => { });
  }, [authToken]);

  useEffect(() => {
    if (!scanning) return;
    
    let scanner: Html5QrcodeScanner | null = null;
    try {
      scanner = new Html5QrcodeScanner(
        "reader",
        { fps: 10, qrbox: { width: 220, height: 220 } },
        false
      );

      scanner.render(
        async (decodedText) => {
          if (scanner) scanner.clear();
          // Both an e-ticket and a travel pass are signed tokens with three
          // segments, so segment count no longer tells them apart. The token
          // declares its own type in the payload; read that to route the scan.
          // This is not verification -- the server still checks the signature,
          // with a different key for each type.
          if (declaredTokenType(decodedText) === "travel_pass") {
            handleVerifyPass(decodedText);
          } else if (decodedText.split(".").length === 3) {
            setLoading(true);
            try {
              const r = await ticketApi.verifyTicket({ qr_token: decodedText });
              setScanResult({
                status: r.success ? "VALID" : "INVALID",
                pass_type: r.success ? "Digital Bus E-Ticket" : "Invalid Token",
                pass_id: r.ticket_id || "E-TICKET",
                reason: r.success ? undefined : r.message,
                verification_mode: "online e-ticket signature check",
                checked_revocation: true,
                route_permission: "Single validated journey",
              });
              setScanCount((prev) => prev + 1);
              playAudioBeep(r.success);
              if (r.success) {
                toast.success("E-Ticket Verified!");
              } else {
                toast.error(`Verification Failed: ${r.message}`);
              }
            } catch (err: any) {
              toast.error(err.message || "Ticket verification error");
              setScanResult({ status: "INVALID", pass_id: "E-TICKET", reason: "Verification error" });
              playAudioBeep(false);
            } finally {
              setLoading(false);
              setScanning(false);
            }
          } else {
            handleVerifyPass(decodedText);
          }
        },
        () => {}
      );
    } catch (e) {
      // Ignore scanner camera initialization if no video device is present
    }

    return () => {
      if (scanner) scanner.clear().catch(() => {});
    };
  }, [scanning, offlineMode]);

  return (
    <div className="page-container" style={{ maxWidth: '650px', margin: '0 auto', padding: '2rem 1rem' }}>
      <div className="bento-card" style={{ padding: '2rem', background: 'var(--surface-glass)', backdropFilter: 'blur(20px)', border: '1px solid var(--line-strong)', borderRadius: '20px' }}>
        
        {/* Header with Mode Pill */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
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
            <h2 className="bento-title" style={{ fontSize: '1.35rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <ScanLine size={24} className="text-accent" /> Conductor Verification Terminal
            </h2>
            <span style={{ fontSize: '0.82rem', color: 'var(--text-3)' }}>BMTC Conductor ID: CND-402 • Route 500-D</span>
          </div>

          <button
            onClick={() => setOfflineMode(!offlineMode)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              borderRadius: '20px',
              fontSize: '0.8rem',
              fontWeight: 700,
              cursor: 'pointer',
              background: offlineMode ? 'rgba(16, 185, 129, 0.15)' : 'var(--surface-strong)',
              color: offlineMode ? '#10b981' : 'var(--text-2)',
              border: `1px solid ${offlineMode ? '#10b981' : 'var(--line-strong)'}`
            }}
          >
            {offlineMode ? <WifiOff size={14} /> : <Zap size={14} />}
            {offlineMode ? "⚡ Sub-Second Offline Scan Mode" : "Cloud Sync Mode"}
          </button>
        </div>

        {/* Quick Demo Scan Simulator Panel */}
        <div style={{ padding: '1rem', background: 'var(--surface-strong)', borderRadius: '12px', marginBottom: '1.5rem', border: '1px solid var(--line-strong)' }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '0.5rem', fontWeight: 600 }}>
            Quick Verification Demo Simulator
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            <button
              className="bento-btn"
              style={{ padding: '6px 12px', fontSize: '0.82rem', background: 'var(--gradient-brand)', color: 'white' }}
              onClick={() => handleVerifyPass("BMTC-PASS-88492")}
            >
              Scan Valid Pass (Student)
            </button>
            <button
              className="bento-btn secondary"
              style={{ padding: '6px 12px', fontSize: '0.82rem' }}
              onClick={() => handleVerifyPass("BMTC-PASS-VOLVO-992")}
            >
              Scan Volvo Pass
            </button>
            <button
              className="bento-btn secondary"
              style={{ padding: '6px 12px', fontSize: '0.82rem', borderColor: '#f43f5e', color: '#f43f5e' }}
              onClick={() => handleVerifyPass("BMTC-PASS-EXPIRED")}
            >
              Scan Expired Pass
            </button>
          </div>
        </div>

        {/* Main Scanner Container */}
        {scanning ? (
          <div>
            <div id="reader" style={{ width: '100%', borderRadius: '12px', overflow: 'hidden', marginBottom: '1rem', border: '1px solid var(--line-strong)' }}></div>
            <p className="text-muted" style={{ textAlign: 'center', fontSize: '0.85rem', margin: 0 }}>
              Position pass QR code within frame or click a simulation button above.
            </p>
          </div>
        ) : loading ? (
          <div style={{ padding: '3rem 0', textAlign: 'center' }}>
            <span className="animate-spin" style={{ display: 'inline-block', width: '32px', height: '32px', border: '3px solid var(--brand)', borderTopColor: 'transparent', borderRadius: '50%', marginBottom: '1rem' }}></span>
            <p style={{ fontWeight: 600, margin: 0 }}>Cryptographically Validating Pass...</p>
          </div>
        ) : scanResult ? (
          <div
            style={{
              padding: '1.75rem',
              borderRadius: '16px',
              textAlign: 'center',
              background: scanResult.status === 'VALID' ? 'rgba(16, 185, 129, 0.12)' : 'rgba(244, 63, 94, 0.12)',
              border: `2px solid ${scanResult.status === 'VALID' ? '#10b981' : '#f43f5e'}`
            }}
          >
            {scanResult.status === 'VALID' ? (
              <CheckCircle size={54} style={{ color: '#10b981', margin: '0 auto 0.75rem auto' }} />
            ) : (
              <XCircle size={54} style={{ color: '#f43f5e', margin: '0 auto 0.75rem auto' }} />
            )}
            
            <h3 style={{ fontSize: '1.4rem', fontWeight: 800, margin: '0 0 0.25rem 0', color: scanResult.status === 'VALID' ? '#10b981' : '#f43f5e' }}>
              {scanResult.status === 'VALID' ? "PASS VERIFIED — VALID" : "SCAN REJECTED — INVALID"}
            </h3>
            
            {scanResult.holder_name && (
              <div style={{ fontSize: '1.1rem', fontWeight: 700, margin: '0.5rem 0' }}>
                {scanResult.holder_name}
              </div>
            )}
            {scanResult.reason && (
              <div style={{ fontSize: '0.9rem', margin: '0.5rem 0', color: '#f43f5e' }}>
                {scanResult.reason}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'center', gap: '0.5rem', margin: '1rem 0', flexWrap: 'wrap' }}>
              {scanResult.pass_type && (
                <span style={{ padding: '4px 12px', borderRadius: '12px', background: 'var(--surface-strong)', border: '1px solid var(--line-strong)', fontSize: '0.82rem', fontWeight: 600 }}>
                  {scanResult.pass_type}
                </span>
              )}
              {scanResult.demo_mode && (
                <span style={{ padding: '4px 12px', borderRadius: '12px', background: '#f59e0b22', border: '1px solid #f59e0b', fontSize: '0.82rem', fontWeight: 700, color: '#f59e0b' }}>
                  DEMO — no signature checked
                </span>
              )}
            </div>

            <div style={{ textAlign: 'left', background: 'var(--surface-strong)', padding: '1rem', borderRadius: '10px', fontSize: '0.82rem', color: 'var(--text-2)', display: 'flex', flexDirection: 'column', gap: '0.35rem', marginBottom: '1.25rem' }}>
              <div><strong>Pass ID:</strong> {scanResult.pass_id ?? "—"}</div>
              <div><strong>Valid until:</strong> {scanResult.valid_until ?? "—"}</div>
              <div><strong>Checked:</strong> {scanResult.verification_mode ?? "—"}</div>
              {/* Whether revocation could be consulted matters to a conductor
                  working from a cached list: a pass cancelled minutes ago may
                  not be reflected yet, and they deserve to know that. */}
              <div><strong>Revocation list:</strong> {scanResult.checked_revocation ? "checked" : "not checked (offline)"}</div>
              <div><strong>Permissions:</strong> {scanResult.route_permission ?? "—"}</div>
            </div>
            
            <button
              onClick={() => {
                setScanResult(null);
                setScanning(true);
              }}
              className="bento-btn"
              style={{ width: '100%', padding: '0.75rem', fontSize: '0.95rem', background: 'var(--gradient-brand)', color: 'white', border: 'none', borderRadius: '10px' }}
            >
              Scan Next Passenger
            </button>
          </div>
        ) : null}

        {/* Telemetry Footer */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid var(--line-strong)', fontSize: '0.78rem', color: 'var(--text-3)' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <ShieldCheck size={14} className="text-accent" /> Cryptographic HMAC Signature Guard
          </span>
          <span>Scans Today: <strong>{scanCount} Passengers</strong></span>
        </div>
      </div>
    </div>
  );
}

