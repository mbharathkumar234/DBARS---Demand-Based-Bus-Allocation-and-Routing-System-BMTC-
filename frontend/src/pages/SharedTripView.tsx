import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertCircle, Bus, MapPin } from "lucide-react";
import { apiFetch } from "../lib/apiClient";

type SharedTrip = {
    current_stop: string;
    destination: string;
    bus_number: string | null;
    shared_at: string;
    expires_at: string;
    note: string;
};

/**
 * Public page (no login required) for a trusted contact to view a shared
 * trip. Deliberately outside ProtectedRoute in App.tsx -- the person
 * checking on someone may not have (or want) an app account.
 *
 * Shows the PLANNED trip only. See safety_service.py's create_trip_share
 * docstring for why this must never be presented as live location.
 */
export default function SharedTripView() {
    const { code } = useParams<{ code: string }>();
    const [trip, setTrip] = useState<SharedTrip | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (!code) return;
        apiFetch(`/safety/trip/${code}`)
            .then(async (res) => {
                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    throw new Error(data.detail || "This trip link has expired or doesn't exist.");
                }
                return res.json();
            })
            .then(setTrip)
            .catch((err) => setError(err instanceof Error ? err.message : "Something went wrong"))
            .finally(() => setLoading(false));
    }, [code]);

    return (
        <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: "1.5rem" }}>
            <div style={{ maxWidth: 420, width: "100%", padding: "2rem", borderRadius: "16px", background: "var(--surface-strong)", border: "1px solid var(--line-strong)" }}>
                {loading && <p className="text-muted">Loading...</p>}

                {!loading && error && (
                    <div style={{ textAlign: "center" }}>
                        <AlertCircle size={28} style={{ color: "#f43f5e", marginBottom: "0.5rem" }} />
                        <p>{error}</p>
                    </div>
                )}

                {!loading && trip && (
                    <>
                        <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>Shared BMTC Trip</h2>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "0.5rem" }}>
                            <MapPin size={16} className="text-accent" />
                            <span>{trip.current_stop} → {trip.destination}</span>
                        </div>
                        {trip.bus_number && (
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "0.5rem" }}>
                                <Bus size={16} className="text-accent" />
                                <span>Bus {trip.bus_number}</span>
                            </div>
                        )}
                        <p className="text-muted" style={{ fontSize: "0.8rem", marginTop: "1rem" }}>{trip.note}</p>
                        <p className="text-muted" style={{ fontSize: "0.72rem" }}>
                            Shared at {new Date(trip.shared_at).toLocaleString()} · link expires {new Date(trip.expires_at).toLocaleString()}
                        </p>
                    </>
                )}
            </div>
        </div>
    );
}