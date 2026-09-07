import { Sparkles, Bot } from "lucide-react";
import { useAI } from "../contexts/AIContext";
import { useAuth } from "../contexts/AuthContext";

export function AIFloatingTrigger() {
  const { toggleAI, isOpen } = useAI();
  const { isAuthenticated } = useAuth();

  if (isOpen) return null;
  // The assistant requires a signed-in account: it answers using the same
  // role-restricted services the REST API exposes. Offering it to a signed-out
  // visitor would only produce a 401 once they typed a question.
  if (!isAuthenticated) return null;

  return (
    <button
      type="button"
      onClick={toggleAI}
      className="fixed bottom-5 right-5 z-[9990] flex items-center gap-2 px-3.5 py-2.5 rounded-full bg-gradient-to-r from-[var(--brand)] to-[var(--brand-2)] text-white shadow-xl hover:shadow-[0_0_20px_rgba(0,198,174,0.45)] hover:scale-105 active:scale-95 transition-all duration-200 border border-white/20 backdrop-blur-md group"
      title="Ask DBARS AI Assistant (Alt+A)"
      aria-label="Open DBARS AI Assistant"
    >
      <div className="relative">
        <Bot size={18} className="text-white" />
        <span className="absolute -top-1 -right-1 flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
        </span>
      </div>
      <span className="font-bold text-xs tracking-wide hidden sm:inline">Ask AI</span>
      <Sparkles size={13} className="text-white/80 group-hover:rotate-12 transition-transform hidden sm:inline" />
    </button>
  );
}
