import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import type { RetrievalMode } from "../services/aiService";

interface AIContextValue {
  isOpen: boolean;
  mode: RetrievalMode;
  initialPrompt: string | null;
  openAI: (initialMode?: RetrievalMode, prompt?: string) => void;
  closeAI: () => void;
  toggleAI: () => void;
  setMode: (mode: RetrievalMode) => void;
}

const AIContext = createContext<AIContextValue | undefined>(undefined);

export function AIProvider({ children }: { children: ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [mode, setMode] = useState<RetrievalMode>("travel");
  const [initialPrompt, setInitialPrompt] = useState<string | null>(null);

  const openAI = (initialMode?: RetrievalMode, prompt?: string) => {
    if (initialMode) setMode(initialMode);
    if (prompt) setInitialPrompt(prompt);
    setIsOpen(true);
  };

  const closeAI = () => {
    setIsOpen(false);
    setInitialPrompt(null);
  };

  const toggleAI = () => {
    setIsOpen((prev) => !prev);
  };

  // Global keyboard shortcuts: Alt+A to toggle, Escape to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.altKey && e.key.toLowerCase() === "a") || (e.ctrlKey && e.key.toLowerCase() === "k")) {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      }
      if (e.key === "Escape" && isOpen) {
        setIsOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  return (
    <AIContext.Provider
      value={{
        isOpen,
        mode,
        initialPrompt,
        openAI,
        closeAI,
        toggleAI,
        setMode,
      }}
    >
      {children}
    </AIContext.Provider>
  );
}

export function useAI(): AIContextValue {
  const context = useContext(AIContext);
  if (!context) {
    throw new Error("useAI must be used within an AIProvider");
  }
  return context;
}
