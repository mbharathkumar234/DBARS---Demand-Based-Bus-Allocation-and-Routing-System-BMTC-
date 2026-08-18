import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { BusFront, Vote, Map, Globe, Sparkles, ArrowRight, BarChart3, Navigation } from "lucide-react";
import { useLanguage } from "../contexts/LanguageContext";

export default function Landing() {
  const { t } = useLanguage();

  const features = [
    { icon: <Sparkles size={28} />, title: t("landing.feature_predict_title"), desc: t("landing.feature_predict_desc"), color: "#6366f1" },
    { icon: <Vote size={28} />, title: t("landing.feature_vote_title"), desc: t("landing.feature_vote_desc"), color: "#f43f5e" },
    { icon: <Navigation size={28} />, title: t("landing.feature_track_title"), desc: t("landing.feature_track_desc"), color: "#10b981" },
    { icon: <Globe size={28} />, title: t("landing.feature_multilingual_title"), desc: t("landing.feature_multilingual_desc"), color: "#f59e0b" },
  ];

  const steps = [
    { num: "01", title: t("landing.step1_title"), desc: t("landing.step1_desc") },
    { num: "02", title: t("landing.step2_title"), desc: t("landing.step2_desc") },
    { num: "03", title: t("landing.step3_title"), desc: t("landing.step3_desc") },
  ];

  return (
    <div className="landing-page">
      {/* Hero */}
      <section className="landing-hero">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7 }}
        >
          <div className="landing-badge">
            <BusFront size={14} /> {t("landing.eyebrow")}
          </div>
          <h1 className="landing-title">{t("landing.title_1")}</h1>
          {/* The name expanded. Its own element rather than a second line of
              the h1: at the hero's 4.5rem the full expansion would wrap to
              three lines and swamp the name it is supposed to explain. */}
          <p className="landing-tagline gradient-text">{t("landing.title_2")}</p>
          <p className="landing-subtitle">{t("landing.subtitle")}</p>

          <div className="landing-cta-group">
            <Link to="/register" className="primary-button">
              {t("landing.cta_register")} <ArrowRight size={16} />
            </Link>
            <Link to="/login" className="secondary-button">
              {t("auth.login_btn")}
            </Link>
          </div>

          <div className="landing-stats">
            <div className="landing-stat"><span className="stat-value">2400+</span><span className="stat-label">{t("landing.stat_routes")}</span></div>
            <div className="landing-stat"><span className="stat-value">8500+</span><span className="stat-label">{t("landing.stat_stops")}</span></div>
            <div className="landing-stat"><span className="stat-value">~50ms</span><span className="stat-label">{t("landing.stat_response")}</span></div>
          </div>
        </motion.div>
      </section>

      {/* Features */}
      <section className="landing-features">
        <div className="bento-grid">
          {features.map((f, i) => (
            <motion.div
              key={i}
              className="bento-card"
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.1 }}
            >
              <div className="qa-icon" style={{ color: f.color, marginBottom: '1rem' }}>{f.icon}</div>
              <h3 className="bento-title">{f.title}</h3>
              <p className="text-muted">{f.desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="landing-steps" style={{ padding: '4rem 0' }}>
        <h2 className="section-title" style={{ marginBottom: '2rem', textAlign: 'center' }}>{t("landing.how_it_works")}</h2>
        <div className="bento-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
          {steps.map((s, i) => (
            <motion.div
              key={i}
              className="bento-card"
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ delay: i * 0.15 }}
            >
              <span className="gradient-text" style={{ fontSize: '2rem', fontWeight: 900 }}>{s.num}</span>
              <h3 className="bento-title">{s.title}</h3>
              <p className="text-muted">{s.desc}</p>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Footer CTA */}
      <section className="landing-footer-cta" style={{ padding: '4rem 0', textAlign: 'center' }}>
        <h2 style={{ marginBottom: '1.5rem' }}>Ready to ride smarter?</h2>
        <Link to="/register" className="primary-button">
          {t("landing.cta_register")} <ArrowRight size={16} />
        </Link>
      </section>
    </div>
  );
}
