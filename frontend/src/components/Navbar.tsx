import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  BusFront, Map, Vote, BarChart3, Globe, LogOut, Menu, X, Truck, User,
  Sparkles, Ticket, ScanLine, Settings, Info, HelpCircle, UserCircle,
  ChevronRight, Home, Navigation, Bot
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { useLanguage, LANGUAGE_LABELS, type Language } from "../contexts/LanguageContext";
import { useAI } from "../contexts/AIContext";
import { ThemeToggle } from "./ThemeToggle";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { MetroMapModal } from "./MetroMapModal";

export default function Navbar() {
  const { user, logout, isAdmin, isDepot, isAuthenticated } = useAuth();
  const { lang, setLang, t } = useLanguage();
  const { openAI } = useAI();
  const [theme, setTheme] = useLocalStorage<"light" | "dark">("bmtc-theme", "dark");
  const [menuOpen, setMenuOpen] = useState(false);
  const [langOpen, setLangOpen] = useState(false);
  const [showMetroModal, setShowMetroModal] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.classList.toggle("dark", next === "dark");
  };

  if (!isAuthenticated && location.pathname === "/") return null;

  const navLinks = isAuthenticated
    ? [
        { to: "/dashboard", icon: <Sparkles size={16} />, label: t("nav.home") },

        // Commuter-only links
        ...(!isAdmin && !isDepot ? [
          { to: "/vote", icon: <Vote size={16} />, label: t("nav.vote") },
          { to: "/predict", icon: <Map size={16} />, label: t("nav.predict") },
          { to: "/tickets", icon: <Ticket size={16} />, label: "Tickets" },
          { to: "/track", icon: <BusFront size={16} />, label: t("nav.track") },
        ] : []),

        // Admin-only links — NO depot access
        ...(isAdmin ? [
          { to: "/admin", icon: <BarChart3 size={16} />, label: t("nav.admin") },
          { to: "/track", icon: <BusFront size={16} />, label: t("nav.track") },
        ] : []),

        // Depot-only links — NO admin access
        ...(isDepot ? [
          { to: "/depot", icon: <Truck size={16} />, label: t("nav.depot") },
          { to: "/scanner", icon: <ScanLine size={16} />, label: "Scanner" },
          { to: "/track", icon: <BusFront size={16} />, label: t("nav.track") },
        ] : []),
      ]
    : [
        { to: "/login", icon: <User size={16} />, label: t("nav.login") },
        { to: "/register", icon: <Sparkles size={16} />, label: t("nav.register") },
      ];

  // Role label for the menu
  const roleLabel = isAdmin ? "Admin Portal" : isDepot ? "Depot Ops" : "Commuter Portal";
  const roleBadgeClass = isAdmin ? "admin" : isDepot ? "depot" : "commuter";

  // Helper: close and navigate
  const go = (path: string) => { setMenuOpen(false); navigate(path); };

  return (
    <header className="topbar">
      <Link to="/" className="brand" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', textDecoration: 'none' }}>
        <div className="brand-icon"><BusFront size={20} /></div>
        <div className="brand-text">
          <strong>DBARS</strong>
          <small>Demand Based Bus Allocation &amp; Routing System</small>
        </div>
        {isAuthenticated && (
          <span className={`portal-badge ${location.pathname.startsWith('/admin') ? 'admin' : (location.pathname.startsWith('/depot') || location.pathname.startsWith('/scanner')) ? 'depot' : 'commuter'}`} style={{ marginLeft: '0.25rem' }}>
            {location.pathname.startsWith('/admin') ? 'Admin Portal' : (location.pathname.startsWith('/depot') || location.pathname.startsWith('/scanner')) ? 'Depot Ops' : 'Commuter Portal'}
          </span>
        )}
      </Link>

      {/* Desktop nav */}
      <nav className="desktop-nav">
        {navLinks.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className={location.pathname === link.to ? "nav-active" : ""}
          >
            {link.icon} <span>{link.label}</span>
          </Link>
        ))}

        {/* Ask AI Trigger Button -- signed-in only; the assistant is authenticated. */}
        {isAuthenticated && (
        <button
          type="button"
          onClick={() => openAI()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold text-white shadow-sm hover:opacity-90 hover:scale-105 active:scale-95 transition-all cursor-pointer"
          style={{ background: "var(--gradient-brand)" }}
          title="Open DBARS AI Assistant (Alt+A)"
        >
          <Bot size={15} />
          <span>Ask AI</span>
          <Sparkles size={12} className="opacity-80" />
        </button>
        )}

        <div className="lang-dropdown">
          <button className="icon-button" onClick={() => setLangOpen(!langOpen)} title="Change language" type="button">
            <Globe size={17} />
          </button>
          {langOpen && (
            <div className="dropdown-menu" onClick={() => setLangOpen(false)}>
              {(Object.keys(LANGUAGE_LABELS) as Language[]).map((l) => (
                <button key={l} className={`dropdown-item ${l === lang ? "active" : ""}`} onClick={() => setLang(l)} type="button">
                  {LANGUAGE_LABELS[l]}
                </button>
              ))}
            </div>
          )}
        </div>

        <ThemeToggle theme={theme} onToggle={toggleTheme} />

        {isAuthenticated && (
          <button className="icon-button" onClick={logout} title={t("nav.logout")} type="button">
            <LogOut size={17} />
          </button>
        )}
      </nav>

      {/* Mobile hamburger */}
      <button className="mobile-menu-btn icon-button" onClick={() => setMenuOpen(!menuOpen)} type="button">
        {menuOpen ? <X size={20} /> : <Menu size={20} />}
      </button>

      {/* ── Mobile Floating Popover ── */}
      {menuOpen && (
        <div className="mobile-nav-overlay" onClick={() => setMenuOpen(false)}>
          <div className="mobile-nav-container" onClick={(e) => e.stopPropagation()}>

            {/* Header */}
            <div className="mobile-nav-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div className="brand-icon" style={{ width: 32, height: 32, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--gradient-brand)' }}>
                  <BusFront size={16} color="white" />
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: '0.95rem', lineHeight: 1.2 }}>DBARS</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', lineHeight: 1 }}>
                    {user?.email || "Navigation Portal"}
                  </div>
                </div>
              </div>
              <span className={`portal-badge ${roleBadgeClass}`} style={{ fontSize: '0.7rem' }}>{roleLabel}</span>
            </div>

            {/* ── Navigation Section ── */}
            <div style={{ marginTop: '1rem' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.4rem', padding: '0 2px' }}>
                Navigation
              </div>
              {navLinks.map((link) => (
                <button
                  key={link.to}
                  type="button"
                  onClick={() => go(link.to)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    width: '100%', background: location.pathname === link.to ? 'var(--gradient-brand-subtle)' : 'none',
                    border: location.pathname === link.to ? '1px solid var(--brand)' : '1px solid transparent',
                    borderRadius: '10px', padding: '10px 12px', marginBottom: '2px', cursor: 'pointer',
                    color: location.pathname === link.to ? 'var(--brand-strong)' : 'var(--text)',
                    fontWeight: location.pathname === link.to ? 700 : 400, fontSize: '0.9rem',
                    textAlign: 'left', transition: 'background 0.15s'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ color: location.pathname === link.to ? 'var(--brand)' : 'var(--text-muted)' }}>{link.icon}</span>
                    {link.label}
                  </div>
                  <ChevronRight size={14} style={{ opacity: 0.4 }} />
                </button>
              ))}
            </div>

            {/* ── Account & Transport Services Section ── */}
            {isAuthenticated && (
              <div style={{ marginTop: '1rem', borderTop: '1px solid var(--line-subtle)', paddingTop: '1rem' }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.4rem', padding: '0 2px' }}>
                  Account & Metro Map
                </div>
                {[
                  { icon: <Bot size={16} style={{ color: 'var(--brand)' }} />, label: "✨ DBARS AI Copilot", action: () => { setMenuOpen(false); openAI(); } },
                  { icon: <Map size={16} style={{ color: 'var(--brand)' }} />, label: "🔍 Enlarge & View Metro Map 2025", action: () => { setMenuOpen(false); setShowMetroModal(true); } },
                  { icon: <UserCircle size={16} />, label: "Profile", action: () => go("/dashboard") },
                  { icon: <Settings size={16} />, label: "Settings", action: () => {} },
                  { icon: <Info size={16} />, label: "About DBARS", action: () => {} },
                  { icon: <HelpCircle size={16} />, label: "Help & Support", action: () => {} },
                ].map(({ icon, label, action }) => (
                  <button
                    key={label}
                    type="button"
                    onClick={action}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      width: '100%', background: 'none', border: '1px solid transparent',
                      borderRadius: '10px', padding: '9px 12px', marginBottom: '2px', cursor: 'pointer',
                      color: 'var(--text)', fontSize: '0.88rem', textAlign: 'left'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{ color: 'var(--text-muted)' }}>{icon}</span>
                      {label}
                    </div>
                    <ChevronRight size={14} style={{ opacity: 0.3 }} />
                  </button>
                ))}
              </div>
            )}

            {/* ── Footer: Language + Theme + Logout ── */}
            <div className="mobile-nav-footer" style={{ marginTop: '1rem', borderTop: '1px solid var(--line-subtle)', paddingTop: '1rem' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.5rem', padding: '0 2px' }}>
                Language
              </div>
              <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                {(Object.keys(LANGUAGE_LABELS) as Language[]).map((l) => (
                  <button
                    key={l}
                    className={`lang-btn ${l === lang ? "active" : ""}`}
                    onClick={() => setLang(l)}
                    type="button"
                    style={{ flex: 1, minWidth: '58px', padding: '6px 10px', borderRadius: '8px', fontSize: '0.8rem', fontWeight: 600, border: '1px solid var(--line-strong)', background: l === lang ? 'var(--gradient-brand)' : 'var(--surface-strong)', color: l === lang ? '#fff' : 'var(--text)', cursor: 'pointer' }}
                  >
                    {LANGUAGE_LABELS[l]}
                  </button>
                ))}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <ThemeToggle theme={theme} onToggle={toggleTheme} />
                {isAuthenticated && (
                  <button
                    onClick={() => { setMenuOpen(false); logout(); }}
                    type="button"
                    style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 16px', borderRadius: '10px', background: 'rgba(244, 63, 94, 0.15)', color: '#f43f5e', border: '1px solid #f43f5e', fontSize: '0.85rem', fontWeight: 700, cursor: 'pointer' }}
                  >
                    <LogOut size={16} /> {t("nav.logout")}
                  </button>
                )}
              </div>
            </div>

          </div>
        </div>
      )}

      {/* Metro Map PDF Viewer Modal */}
      <MetroMapModal isOpen={showMetroModal} onClose={() => setShowMetroModal(false)} />
    </header>
  );
}
