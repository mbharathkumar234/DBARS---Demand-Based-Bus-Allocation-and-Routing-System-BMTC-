import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { BusFront, Loader2, UserPlus } from "lucide-react";
import { useAuth, type Gender } from "../contexts/AuthContext";
import { useLanguage, LANGUAGE_LABELS, type Language } from "../contexts/LanguageContext";
import toast from "react-hot-toast";

export default function Register() {
  const { register } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [form, setForm] = useState<{
    name: string; email: string; password: string; phone: string;
    preferred_lang: string; role: string; gender: Gender | "";
  }>({
    name: "", email: "", password: "", phone: "",
    preferred_lang: "en", role: "commuter", gender: "",
  });
  const [loading, setLoading] = useState(false);

  const update = (field: string, value: string) => setForm({ ...form, [field]: value });

  // Only women and transgender passengers travel free under the scheme, and
  // only on ordinary (non-AC) services -- the AC caveat is shown at purchase,
  // where it actually applies, rather than as a footnote here.
  const shaktiEligible = form.gender === "female" || form.gender === "transgender";

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await register(form);
      toast.success("Account created!");
      navigate("/dashboard");
    } catch (err: any) {
      toast.error(err.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <motion.div
        className="auth-card"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <div className="auth-header">
          <div className="brand-icon"><BusFront size={24} /></div>
          <h1>{t("auth.register_title")}</h1>
          <p>{t("auth.register_subtitle")}</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label>{t("auth.name")}</label>
            <input type="text" value={form.name} onChange={(e) => update("name", e.target.value)} required placeholder="Bharath Kumar" />
          </div>
          <div className="form-group">
            <label>{t("auth.email")}</label>
            <input type="email" value={form.email} onChange={(e) => update("email", e.target.value)} required placeholder="you@example.com" />
          </div>
          <div className="form-group">
            <label>{t("auth.password")}</label>
            <input type="password" value={form.password} onChange={(e) => update("password", e.target.value)} required minLength={6} placeholder="Minimum 6 characters" />
          </div>
          <div className="form-group">
            <label>{t("auth.phone")}</label>
            <input type="tel" value={form.phone} onChange={(e) => update("phone", e.target.value)} placeholder="+91 98765 43210" />
          </div>
          <div className="form-group">
            <label>{t("auth.gender")}</label>
            <select value={form.gender} onChange={(e) => update("gender", e.target.value)}>
              <option value="">{t("auth.gender_unset")}</option>
              <option value="female">{t("auth.gender_female")}</option>
              <option value="male">{t("auth.gender_male")}</option>
              <option value="transgender">{t("auth.gender_transgender")}</option>
              <option value="prefer_not_to_say">{t("auth.gender_private")}</option>
            </select>
            {/* Said plainly at the point of asking. A sensitive question with
                no stated purpose reads as data collection for its own sake;
                this one buys the passenger a real entitlement. */}
            <p style={{ fontSize: "0.74rem", color: "var(--text-3)", margin: "6px 0 0 0", lineHeight: 1.45 }}>
              {t("auth.gender_why")}
            </p>
            {shaktiEligible && (
              <p style={{ fontSize: "0.76rem", color: "#10b981", fontWeight: 600, margin: "4px 0 0 0", lineHeight: 1.45 }}>
                {t("auth.gender_shakti_ok")}
              </p>
            )}
          </div>

          <div className="form-group">
            <label>{t("auth.language")}</label>
            <select value={form.preferred_lang} onChange={(e) => update("preferred_lang", e.target.value)}>
              {(Object.keys(LANGUAGE_LABELS) as Language[]).map((l) => (
                <option key={l} value={l}>{LANGUAGE_LABELS[l]}</option>
              ))}
            </select>
          </div>

          <button type="submit" className="primary-button auth-submit" disabled={loading}>
            {loading ? <Loader2 className="animate-spin" size={18} /> : <UserPlus size={18} />}
            <span>{loading ? t("common.loading") : t("auth.register_btn")}</span>
          </button>
        </form>

        <div className="auth-footer">
          <p>{t("auth.has_account")} <Link to="/login">{t("nav.login")}</Link></p>
        </div>
      </motion.div>
    </div>
  );
}
