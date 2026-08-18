import { createContext, useContext, useState, useEffect, ReactNode } from "react";

import en from "../i18n/en.json";
import kn from "../i18n/kn.json";
import hi from "../i18n/hi.json";
import te from "../i18n/te.json";

export type Language = "en" | "kn" | "hi" | "te";

const translations: Record<Language, Record<string, any>> = { en, kn, hi, te };

export const LANGUAGE_LABELS: Record<Language, string> = {
  en: "English",
  kn: "ಕನ್ನಡ",
  hi: "हिन्दी",
  te: "తెలుగు",
};

interface LanguageContextType {
  lang: Language;
  setLang: (lang: Language) => void;
  t: (key: string) => string;
}

const LanguageContext = createContext<LanguageContextType>({
  lang: "en",
  setLang: () => {},
  t: (key: string) => key,
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Language>(() => {
    const saved = localStorage.getItem("bmtc-lang");
    return (saved as Language) || "en";
  });

  const setLang = (newLang: Language) => {
    setLangState(newLang);
    localStorage.setItem("bmtc-lang", newLang);
  };

  const t = (key: string): string => {
    const keys = key.split(".");
    let value: any = translations[lang];
    for (const k of keys) {
      value = value?.[k];
    }
    if (typeof value === "string") return value;
    // Fallback to English
    let fallback: any = translations.en;
    for (const k of keys) {
      fallback = fallback?.[k];
    }
    return typeof fallback === "string" ? fallback : key;
  };

  return (
    <LanguageContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export const useLanguage = () => useContext(LanguageContext);
