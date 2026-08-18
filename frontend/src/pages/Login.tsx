import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { BusFront, Loader2, LogIn } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { useLanguage } from "../contexts/LanguageContext";
import toast from "react-hot-toast";

export default function Login() {
  const { login } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      toast.success("Welcome back!");
      navigate("/dashboard");
    } catch (err: any) {
      toast.error(err.message || "Login failed");
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
          <div className="brand-icon" style={{ margin: '0 auto' }}><BusFront size={24} /></div>
          <h1>{t("auth.login_title")}</h1>
          <p>{t("auth.login_subtitle")}</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label>{t("auth.email")}</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@example.com" />
          </div>
          <div className="form-group">
            <label>{t("auth.password")}</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required placeholder="••••••••" />
          </div>

          <button type="submit" className="primary-button" disabled={loading}>
            {loading ? <Loader2 className="animate-spin" size={18} /> : <LogIn size={18} />}
            <span>{loading ? t("common.loading") : t("auth.login_btn")}</span>
          </button>
        </form>

        <div className="auth-footer">
          <p>{t("auth.no_account")} <Link to="/register" className="text-accent">{t("nav.register")}</Link></p>
        </div>

        <div className="auth-demo-hint">
          <p><strong>Demo accounts:</strong></p>
          <p>Admin: admin@bmtc.ai / admin123</p>
          <p>Depot: depot@bmtc.ai / depot123</p>
        </div>
      </motion.div>
    </div>
  );
}
