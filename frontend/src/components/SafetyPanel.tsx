import { useEffect, useState } from "react";
import { Phone, Share2, ShieldAlert, X } from "lucide-react";
import toast from "react-hot-toast";
import { useAuth } from "../contexts/AuthContext";
import { apiFetch } from "../lib/apiClient";

type TrustedContact = { name: string; phone: string };

type Props = {
    currentStop?: string;
    destination?: string;
    busNumber?: string;
    matchedCurrentStop?: string;
    matchedDestination?: string;
};

/**
 * Real safety features: share a planned trip with a trusted contact, and
 * quick-dial/quick-text the user's own saved contacts via the device's
 * native phone app.
 *
 * DELIBERATELY NOT INCLUDED: any "SOS" button that claims to alert police
 * or emergency services. This app has no real connection to any emergency
 * dispatch system -- a button that looked like it did would be actively
 * dangerous in a real emergency if someone trusted it instead of calling
 * real help. The one thing this panel does in a real emergency is point
 * to the real number: 112 (India's national emergency number), via a
 * plain tel: link that dials it directly, same as any other phone call.
 */
export function SafetyPanel({ currentStop, destination, busNumber, matchedCurrentStop, matchedDestination }: Props) {
    const { token } = useAuth();
    const [open, setOpen] = useState(false);
    const [contacts, setContacts] = useState<TrustedContact[]>([]);
    const [newName, setNewName] = useState("");
    const [newPhone, setNewPhone] = useState("");
    const [shareLink, setShareLink] = useState<string | null>(null);
    const [sharing, setSharing] = useState(false);

    useEffect(() => {
        if (!open || !token) return;
        apiFetch("/safety/contacts", { headers: { Authorization: `Bearer ${token}` } })
            .then((res) => (res.ok ? res.json() : { contacts: [] }))
            .then((data) => setContacts(data.contacts || []))
            .catch(() => { });
    }, [open, token]);

    const addContact = async () => {
        if (!token) {
            toast.error("Log in to save trusted contacts");
            return;
        }
        if (!newName.trim() || !newPhone.trim()) return;
        const updated = [...contacts, { name: newName.trim(), phone: newPhone.trim() }];
        try {
            const res = await apiFetch("/safety/contacts", {
                method: "PUT",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ contacts: updated }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Could not save contact");
            setContacts(data.contacts);
            setNewName("");
            setNewPhone("");
        } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not save contact");
        }
    };

    const removeContact = async (index: number) => {
        if (!token) return;
        const updated = contacts.filter((_, i) => i !== index);
        const res = await apiFetch("/safety/contacts", {
            method: "PUT",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
            body: JSON.stringify({ contacts: updated }),
        });
        if (res.ok) setContacts((await res.json()).contacts);
    };

    const shareTrip = async () => {
        if (!token) {
            toast.error("Log in to share your trip");
            return;
        }
        if (!currentStop || !destination) return;
        setSharing(true);
        try {
            const res = await apiFetch("/safety/share-trip", {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({
                    current_stop: currentStop,
                    destination,
                    bus_number: busNumber,
                    matched_current_stop: matchedCurrentStop,
                    matched_destination: matchedDestination,
                }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || "Could not create share link");
            const base = import.meta.env.VITE_PUBLIC_APP_URL || window.location.origin;
            const link = `${base}/trip/${data.code}`;
            setShareLink(link);
            if (navigator.share) {
                navigator.share({ title: "My BMTC trip", text: "Here's my planned bus trip", url: link }).catch(() => { });
            }
        } catch (err) {
            toast.error(err instanceof Error ? err.message : "Could not create share link");
        } finally {
            setSharing(false);
        }
    };

    return (
        <div style={{ marginTop: '1.25rem' }}>
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="bento-btn secondary"
                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '0.82rem', padding: '6px 14px' }}
            >
                <ShieldAlert size={15} /> Safety
            </button>

            {open && (
                <div style={{ marginTop: '0.75rem', padding: '1rem 1.1rem', background: 'var(--surface-strong)', borderRadius: '14px', border: '1px solid var(--line-strong)' }}>
                    {/* Real emergency number -- a plain tel: link, nothing else */}
                    <a
                        href="tel:112"
                        style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 10px', borderRadius: '10px', background: 'rgba(244, 63, 94, 0.12)', border: '1px solid #f43f5e50', color: '#f43f5e', fontWeight: 700, fontSize: '0.85rem', textDecoration: 'none', marginBottom: '1rem' }}
                    >
                        <Phone size={16} /> Call 112 (India Emergency Number)
                    </a>
                    <p className="text-muted" style={{ fontSize: '0.76rem', margin: '-0.6rem 0 1rem 0' }}>
                        This app isn't connected to emergency services — this dials 112 directly, same as calling from your phone's dialer.
                    </p>

                    {/* Share planned trip */}
                    {currentStop && destination && (
                        <div style={{ marginBottom: '1rem' }}>
                            <button
                                type="button"
                                onClick={shareTrip}
                                disabled={sharing}
                                className="bento-btn"
                                style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '0.82rem', padding: '6px 14px' }}
                            >
                                <Share2 size={14} /> {sharing ? "Creating link..." : "Share this trip"}
                            </button>
                            <p className="text-muted" style={{ fontSize: '0.76rem', margin: '0.4rem 0 0 0' }}>
                                Shares your planned route (not live location — this app doesn't have real-time GPS tracking).
                            </p>
                            {shareLink && (
                                <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                                    <input readOnly value={shareLink} style={{ flex: 1, fontSize: '0.78rem', padding: '6px 8px', borderRadius: '8px', border: '1px solid var(--line-strong)', background: 'var(--surface)' }} onClick={(e) => (e.target as HTMLInputElement).select()} />
                                    <button type="button" className="bento-btn secondary" style={{ fontSize: '0.76rem', padding: '5px 10px' }} onClick={() => { navigator.clipboard?.writeText(shareLink); toast.success("Link copied"); }}>
                                        Copy
                                    </button>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Trusted contacts -- real tel:/sms: links to the user's own saved numbers */}
                    <div>
                        <strong style={{ fontSize: '0.82rem' }}>Trusted contacts</strong>
                        {contacts.length === 0 && (
                            <p className="text-muted" style={{ fontSize: '0.78rem', margin: '0.3rem 0' }}>No contacts saved yet.</p>
                        )}
                        {contacts.map((c, i) => (
                            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.4rem' }}>
                                <span style={{ fontSize: '0.82rem', flex: 1 }}>{c.name}</span>
                                <a href={`tel:${c.phone}`} className="bento-btn secondary" style={{ padding: '4px 8px', fontSize: '0.75rem' }}>Call</a>
                                <a href={`sms:${c.phone}`} className="bento-btn secondary" style={{ padding: '4px 8px', fontSize: '0.75rem' }}>Text</a>
                                <button type="button" onClick={() => removeContact(i)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-3)' }}>
                                    <X size={14} />
                                </button>
                            </div>
                        ))}
                        {contacts.length < 5 && (
                            <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.6rem' }}>
                                <input placeholder="Name" value={newName} onChange={(e) => setNewName(e.target.value)} style={{ flex: 1, fontSize: '0.78rem', padding: '5px 8px', borderRadius: '8px', border: '1px solid var(--line-strong)', background: 'var(--surface)' }} />
                                <input placeholder="Phone" value={newPhone} onChange={(e) => setNewPhone(e.target.value)} style={{ flex: 1, fontSize: '0.78rem', padding: '5px 8px', borderRadius: '8px', border: '1px solid var(--line-strong)', background: 'var(--surface)' }} />
                                <button type="button" onClick={addContact} className="bento-btn secondary" style={{ fontSize: '0.76rem', padding: '5px 10px' }}>Add</button>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}