import { FormEvent, useEffect, useRef, useState, type ReactNode } from "react";
import {
  X,
  Send,
  Sparkles,
  Bot,
  User,
  ShieldCheck,
  AlertCircle,
  HelpCircle,
  Wrench,
  FileCode2,
  Maximize2,
  Minimize2,
  Trash2,
  Compass,
  Zap,
  Code2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  RotateCcw,
  CheckCircle2,
  Layers,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useAuth } from "../contexts/AuthContext";
import { useAI } from "../contexts/AIContext";
import {
  sendAIChat,
  clearAISession,
  type AIChatResponse,
  type Citation,
  type ToolExecutionRecord,
  type GroundingConfidence,
  type RetrievalMode,
} from "../services/aiService";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  grounding?: GroundingConfidence;
  sources?: Citation[];
  toolsCalled?: ToolExecutionRecord[];
  modelUsed?: string;
  latencyMs?: number;
  timestamp: number;
}

const MODE_CONFIG: Record<
  RetrievalMode,
  { label: string; icon: any; placeholder: string; suggestions: string[]; description: string }
> = {
  travel: {
    label: "Commuter Travel",
    icon: Compass,
    placeholder: "Ask route questions, e.g. 'Majestic to Whitefield with least walking'...",
    description: "Point-to-point transit routes, bus availability, 1-transfer connections & Kannada/Hindi queries.",
    suggestions: [
      "How do I travel from Majestic to Whitefield?",
      "Which option involves the least walking from Silk Board to Marathahalli?",
      "What buses run between Banashankari and Electronic City?",
      "KBS inda ITPL ge direct bus idiya?",
    ],
  },
  operations: {
    label: "Depot & Fleet Ops",
    icon: Zap,
    placeholder: "Ask operations questions, e.g. 'How many buses required in fleet plan?'...",
    description: "Bipartite vehicle blocking, crew shift ratios, crowding diagnostics & live service alerts.",
    suggestions: [
      "How many buses are required for the minimum fleet plan?",
      "What is the crew-to-bus ratio and duties required?",
      "Are there active service alerts or corridor disruptions?",
      "Which routes experience frequent passenger crowding?",
    ],
  },
  code: {
    label: "Code & Architecture",
    icon: Code2,
    placeholder: "Ask architecture questions, e.g. 'Where is BMTCBusPredictor implemented?'...",
    description: "AST codebase exploration, deterministic BFS routing algorithms, and GTFS integration.",
    suggestions: [
      "Where is BMTCBusPredictor implemented and how does it rank?",
      "Explain how ordered stop-pair segment indexing works in predictor.py",
      "Where is the Shakti free travel scheme validated?",
      "Trace the full application startup flow in main.py",
    ],
  },
  auto: {
    label: "Smart Auto",
    icon: Sparkles,
    placeholder: "Ask any DBARS travel, operations, or technical question...",
    description: "Intelligently classifies your query across travel, operations, or codebase domains.",
    suggestions: [
      "How do I reach Whitefield from Majestic?",
      "How many total buses are needed in the blocking plan?",
      "Explain how block_interlined chains trips in blocking.py",
    ],
  },
  documentation: {
    label: "Docs & Manuals",
    icon: Layers,
    placeholder: "Ask documentation questions...",
    description: "Query project design documents, requirements, and user guides.",
    suggestions: ["Summarize the DBARS transit architecture", "Explain offline pass verification"],
  },
  routing: {
    label: "Routing Engine",
    icon: Compass,
    placeholder: "Ask routing engine questions...",
    description: "Direct access to DBARS transit algorithms.",
    suggestions: ["Search route from Silk Board to Hebbal"],
  },
  hybrid: {
    label: "Hybrid Search",
    icon: Sparkles,
    placeholder: "Ask comprehensive hybrid questions...",
    description: "Combines semantic embeddings and exact BM25 keywords.",
    suggestions: ["Explain candidate ranking with stop_pair_to_segments"],
  },
};

export function AIAssistantModal() {
  const { isOpen, closeAI, mode, setMode, initialPrompt } = useAI();
  const { user } = useAuth();

  const [sessionId, setSessionId] = useState<string>(() => `sess_${Math.random().toString(36).slice(2, 11)}`);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [isFullScreen, setIsFullScreen] = useState(false);
  const [expandedCitations, setExpandedCitations] = useState<Record<string, boolean>>({});
  const [expandedTools, setExpandedTools] = useState<Record<string, boolean>>({});

  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input when opened or mode changed
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 150);
      if (initialPrompt && !input) {
        setInput(initialPrompt);
      }
    }
  }, [isOpen, initialPrompt]);

  // Scroll to bottom on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  if (!isOpen) return null;

  const handleSend = async (queryText?: string) => {
    const textToSend = (queryText || input).trim();
    if (!textToSend || loading) return;

    const userMessage: ChatMessage = {
      id: `msg_user_${Date.now()}`,
      role: "user",
      content: textToSend,
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    try {
      const response: AIChatResponse = await sendAIChat({
        query: textToSend,
        session_id: sessionId,
        user_id: user?.id ? String(user.id) : (user?.email || null),
        retrieval_mode: mode,
        include_sources: true,
      });

      const assistantMessage: ChatMessage = {
        id: `msg_asst_${Date.now()}`,
        role: "assistant",
        content: response.answer,
        grounding: response.grounding,
        sources: response.sources || [],
        toolsCalled: response.tools_called || [],
        modelUsed: response.model_used,
        latencyMs: response.latency_ms,
        timestamp: Date.now(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err: any) {
      const errorMessage: ChatMessage = {
        id: `msg_err_${Date.now()}`,
        role: "assistant",
        content: `⚠️ Error: ${err.message || "Unable to reach the DBARS AI Assistant. Please verify that the backend is running."}`,
        grounding: "UNKNOWN",
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  };

  const handleClearSession = async () => {
    try {
      await clearAISession(sessionId);
    } catch {
      // Non-blocking
    }
    const newSession = `sess_${Math.random().toString(36).slice(2, 11)}`;
    setSessionId(newSession);
    setMessages([]);
    setExpandedCitations({});
    setExpandedTools({});
  };

  const toggleCitation = (msgId: string) => {
    setExpandedCitations((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  const toggleTools = (msgId: string) => {
    setExpandedTools((prev) => ({ ...prev, [msgId]: !prev[msgId] }));
  };

  const currentModeConfig = MODE_CONFIG[mode] || MODE_CONFIG.travel;

  const renderFormattedMarkdown = (text: string) => {
    const lines = text.split("\n");
    const elements: ReactNode[] = [];

    lines.forEach((line, index) => {
      const trimmed = line.trim();

      // Heading 3
      if (trimmed.startsWith("### ")) {
        elements.push(
          <h3
            key={`h3-${index}`}
            className="text-base font-bold mt-3 mb-1.5 flex items-center gap-1.5 text-[var(--brand-strong)]"
          >
            {trimmed.slice(4)}
          </h3>
        );
        return;
      }

      // Heading 2 or 1
      if (trimmed.startsWith("## ")) {
        elements.push(
          <h2 key={`h2-${index}`} className="text-lg font-extrabold mt-3.5 mb-2 text-[var(--text)]">
            {trimmed.slice(3)}
          </h2>
        );
        return;
      }

      // Alerts: > [!NOTE] or > [!TIP]
      if (trimmed.startsWith("> [!NOTE]")) {
        elements.push(
          <div
            key={`note-${index}`}
            className="my-2 p-2.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-xs text-[var(--text)] flex items-start gap-2"
          >
            <ShieldCheck size={16} className="text-blue-400 mt-0.5 shrink-0" />
            <span className="font-semibold text-blue-400">NOTE:</span>
          </div>
        );
        return;
      }

      if (trimmed.startsWith("> [!TIP]")) {
        elements.push(
          <div
            key={`tip-${index}`}
            className="my-2 p-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-xs text-[var(--text)] flex items-start gap-2"
          >
            <Sparkles size={16} className="text-emerald-400 mt-0.5 shrink-0" />
            <span className="font-semibold text-emerald-400">TIP:</span>
          </div>
        );
        return;
      }

      if (trimmed.startsWith("> ")) {
        elements.push(
          <div
            key={`quote-${index}`}
            className="pl-3 py-0.5 border-l-2 border-[var(--brand)] italic text-xs text-[var(--muted)] my-1"
          >
            {trimmed.slice(2)}
          </div>
        );
        return;
      }

      // Bullet items
      if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        elements.push(
          <div key={`li-${index}`} className="flex items-start gap-2 my-1 text-xs leading-relaxed">
            <span className="text-[var(--brand)] font-bold mt-0.5">•</span>
            <span>{parseInlineFormatting(trimmed.slice(2))}</span>
          </div>
        );
        return;
      }

      // Numbered list
      const numMatch = trimmed.match(/^(\d+)\.\s+(.*)$/);
      if (numMatch) {
        elements.push(
          <div key={`num-${index}`} className="flex items-start gap-2 my-1 text-xs leading-relaxed">
            <span className="text-[var(--brand-2)] font-bold">{numMatch[1]}.</span>
            <span>{parseInlineFormatting(numMatch[2])}</span>
          </div>
        );
        return;
      }

      // Empty line
      if (!trimmed) {
        elements.push(<div key={`sp-${index}`} className="h-1.5" />);
        return;
      }

      // Regular paragraph
      elements.push(
        <p key={`p-${index}`} className="my-1 text-xs leading-relaxed">
          {parseInlineFormatting(trimmed)}
        </p>
      );
    });

    return elements;
  };

  const parseInlineFormatting = (text: string): (string | ReactNode)[] => {
    // Regex matches inline code `code` or bold **bold**
    const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith("`") && part.endsWith("`")) {
        return (
          <code
            key={`code-${i}`}
            className="px-1.5 py-0.5 rounded bg-black/20 dark:bg-white/10 font-mono text-[0.72rem] text-[var(--brand-strong)] border border-[var(--line)]"
          >
            {part.slice(1, -1)}
          </code>
        );
      }
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={`bold-${i}`} className="font-bold text-[var(--text)]">
            {part.slice(2, -2)}
          </strong>
        );
      }
      return part;
    });
  };

  return (
    <AnimatePresence>
      <div
        className="fixed inset-0 z-[99999] flex items-center justify-center bg-black/70 backdrop-blur-md transition-all p-2 sm:p-4"
        onClick={closeAI}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.94, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.94, y: 15 }}
          transition={{ duration: 0.2 }}
          onClick={(e) => e.stopPropagation()}
          className="flex flex-col bg-[var(--bg)] border border-[var(--line-strong)] rounded-2xl shadow-2xl overflow-hidden w-full transition-all"
          style={{
            maxWidth: isFullScreen ? "100vw" : "960px",
            height: isFullScreen ? "100vh" : "88vh",
            borderRadius: isFullScreen ? "0" : "18px",
          }}
        >
          {/* Header Bar */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--line)] bg-[var(--surface-strong)]">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-gradient-to-tr from-[var(--brand)] to-[var(--brand-2)] text-white shadow-md">
                <Bot size={18} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm sm:text-base font-bold text-[var(--text)] tracking-tight">
                    DBARS AI Copilot
                  </h2>
                  <span className="hidden sm:inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    <CheckCircle2 size={10} /> Deterministic Grounding
                  </span>
                </div>
                <p className="text-[11px] text-[var(--muted)] hidden sm:block">
                  Codebase-aware • Timetable-grounded • Zero hallucination
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={handleClearSession}
                className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--line)] transition-colors text-xs flex items-center gap-1"
                title="Start new conversation / clear memory"
              >
                <Trash2 size={14} />
                <span className="hidden sm:inline">New Chat</span>
              </button>

              <button
                type="button"
                onClick={() => setIsFullScreen(!isFullScreen)}
                className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--line)] transition-colors"
                title={isFullScreen ? "Restore size" : "Expand to fullscreen"}
              >
                {isFullScreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
              </button>

              <button
                type="button"
                onClick={closeAI}
                className="p-1.5 rounded-lg text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--line)] transition-colors ml-1"
                title="Close AI Assistant (Esc)"
              >
                <X size={18} />
              </button>
            </div>
          </div>

          {/* Mode Selector Tabs */}
          <div className="flex items-center gap-1.5 px-4 py-2 border-b border-[var(--line)] bg-[var(--surface-muted)] overflow-x-auto scrollbar-none">
            {(["travel", "operations", "code", "auto"] as RetrievalMode[]).map((m) => {
              const cfg = MODE_CONFIG[m];
              const Icon = cfg.icon;
              const isActive = mode === m;
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                    isActive
                      ? "bg-gradient-to-r from-[var(--brand)] to-[var(--brand-2)] text-white shadow-sm"
                      : "text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--line)]"
                  }`}
                >
                  <Icon size={14} />
                  <span>{cfg.label}</span>
                </button>
              );
            })}
          </div>

          {/* Mode Description Banner */}
          <div className="px-4 py-1.5 bg-[var(--surface-glass)] text-[11px] text-[var(--muted)] border-b border-[var(--line)] flex items-center justify-between">
            <span>{currentModeConfig.description}</span>
            <span className="hidden sm:inline font-mono opacity-60">ID: {sessionId.slice(0, 8)}</span>
          </div>

          {/* Chat Messages Log */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-6 max-w-lg mx-auto">
                <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-[var(--brand)]/20 to-[var(--brand-2)]/20 border border-[var(--brand)]/30 flex items-center justify-center text-[var(--brand)] mb-3">
                  <currentModeConfig.icon size={28} />
                </div>
                <h3 className="text-base font-bold text-[var(--text)] mb-1">
                  {currentModeConfig.label} Mode
                </h3>
                <p className="text-xs text-[var(--muted)] mb-5">
                  Ask any transit, scheduling, or technical question. All answers are grounded with verified evidence.
                </p>

                {/* Suggestions Grid */}
                <div className="w-full text-left">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--muted)] mb-2">
                    Suggested Queries
                  </p>
                  <div className="grid grid-cols-1 gap-1.5">
                    {currentModeConfig.suggestions.map((suggestion, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => handleSend(suggestion)}
                        className="text-left text-xs p-2.5 rounded-xl border border-[var(--line)] bg-[var(--surface-strong)] hover:border-[var(--brand)] hover:bg-[var(--gradient-brand-subtle)] transition-all flex items-center justify-between group"
                      >
                        <span className="text-[var(--text)] group-hover:text-[var(--brand-strong)] font-medium">
                          {suggestion}
                        </span>
                        <ChevronRight
                          size={13}
                          className="text-[var(--muted)] group-hover:text-[var(--brand-strong)] group-hover:translate-x-0.5 transition-all shrink-0"
                        />
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : (
              messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  {msg.role === "assistant" && (
                    <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--brand)] to-[var(--brand-2)] text-white flex items-center justify-center shrink-0 mt-1 shadow-sm">
                      <Bot size={15} />
                    </div>
                  )}

                  <div
                    className={`max-w-[85%] sm:max-w-[78%] rounded-2xl p-3.5 sm:p-4 text-xs shadow-sm ${
                      msg.role === "user"
                        ? "bg-gradient-to-r from-[var(--brand)] to-[var(--brand-2)] text-white rounded-br-none"
                        : "bg-[var(--surface-strong)] border border-[var(--line-strong)] text-[var(--text)] rounded-tl-none"
                    }`}
                  >
                    {/* Assistant Message Header */}
                    {msg.role === "assistant" && (
                      <div className="flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-[var(--line)] text-[10px]">
                        <div className="flex items-center gap-1.5">
                          {/* Grounding Status Badge */}
                          {msg.grounding === "CONFIRMED" ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-bold bg-emerald-500/15 text-emerald-500 border border-emerald-500/30">
                              <CheckCircle2 size={10} /> CONFIRMED
                            </span>
                          ) : msg.grounding === "INFERRED" ? (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-bold bg-amber-500/15 text-amber-500 border border-amber-500/30">
                              <AlertCircle size={10} /> INFERRED
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-bold bg-gray-500/15 text-gray-400 border border-gray-500/30">
                              <HelpCircle size={10} /> UNKNOWN
                            </span>
                          )}

                          {msg.latencyMs && (
                            <span className="text-[var(--muted)] font-mono">{msg.latencyMs}ms</span>
                          )}
                        </div>

                        {msg.modelUsed && (
                          <span className="text-[var(--muted)] font-mono opacity-80 truncate max-w-[120px]">
                            {msg.modelUsed}
                          </span>
                        )}
                      </div>
                    )}

                    {/* Content */}
                    <div className="space-y-1">{renderFormattedMarkdown(msg.content)}</div>

                    {/* Tools Called Accordion */}
                    {msg.toolsCalled && msg.toolsCalled.length > 0 && (
                      <div className="mt-3 pt-2 border-t border-[var(--line)]">
                        <button
                          type="button"
                          onClick={() => toggleTools(msg.id)}
                          className="flex items-center justify-between w-full text-[11px] font-bold text-[var(--brand-strong)] hover:underline"
                        >
                          <span className="flex items-center gap-1.5">
                            <Wrench size={12} />
                            <span>Tools Executed ({msg.toolsCalled.length})</span>
                          </span>
                          {expandedTools[msg.id] ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                        </button>

                        {expandedTools[msg.id] && (
                          <div className="mt-2 space-y-1.5">
                            {msg.toolsCalled.map((tool, tIdx) => (
                              <div
                                key={tIdx}
                                className="p-2 rounded-lg bg-black/20 dark:bg-white/5 border border-[var(--line)] text-[11px]"
                              >
                                <div className="flex items-center justify-between font-mono font-bold text-[var(--brand-strong)]">
                                  <span>`{tool.tool_name}`</span>
                                  <span className="text-[10px] text-[var(--muted)]">
                                    {tool.execution_time_ms}ms ({tool.status})
                                  </span>
                                </div>
                                {tool.arguments && Object.keys(tool.arguments).length > 0 && (
                                  <div className="mt-1 text-[10px] text-[var(--muted)] font-mono truncate">
                                    args: {JSON.stringify(tool.arguments)}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Citations & Evidence Accordion */}
                    {msg.sources && msg.sources.length > 0 && (
                      <div className="mt-2.5 pt-2 border-t border-[var(--line)]">
                        <button
                          type="button"
                          onClick={() => toggleCitation(msg.id)}
                          className="flex items-center justify-between w-full text-[11px] font-bold text-[var(--muted)] hover:text-[var(--text)] transition-colors"
                        >
                          <span className="flex items-center gap-1.5">
                            <FileCode2 size={12} />
                            <span>Verified Citations ({msg.sources.length})</span>
                          </span>
                          {expandedCitations[msg.id] ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                        </button>

                        {expandedCitations[msg.id] && (
                          <div className="mt-2 space-y-2">
                            {msg.sources.map((cit, cIdx) => (
                              <div
                                key={cIdx}
                                className="p-2 rounded-lg bg-black/25 dark:bg-white/5 border border-[var(--line)] text-[10px]"
                              >
                                <div className="flex items-center justify-between font-semibold text-[var(--text)]">
                                  <span className="truncate">{cit.title || cit.path}</span>
                                  <span className="uppercase text-[9px] px-1 py-0.5 rounded bg-[var(--line)] text-[var(--brand)]">
                                    {cit.source_type}
                                  </span>
                                </div>
                                {cit.path && (
                                  <div className="font-mono text-[9px] text-[var(--muted)] truncate">
                                    {cit.path} {cit.start_line ? `(L${cit.start_line}-${cit.end_line})` : ""}
                                    {cit.symbol ? ` [${cit.symbol}]` : ""}
                                  </div>
                                )}
                                {cit.snippet && (
                                  <pre className="mt-1 p-1.5 rounded bg-black/40 font-mono text-[9px] text-[var(--text-2)] whitespace-pre-wrap max-h-24 overflow-y-auto border border-black/20">
                                    {cit.snippet}
                                  </pre>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {msg.role === "user" && (
                    <div className="w-7 h-7 rounded-lg bg-[var(--surface-strong)] border border-[var(--line)] text-[var(--text)] flex items-center justify-center shrink-0 mt-1 shadow-sm">
                      <User size={15} />
                    </div>
                  )}
                </div>
              ))
            )}

            {/* Loading Indicator */}
            {loading && (
              <div className="flex items-start gap-3">
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--brand)] to-[var(--brand-2)] text-white flex items-center justify-center shrink-0 mt-1 shadow-sm">
                  <Bot size={15} />
                </div>
                <div className="p-3.5 rounded-2xl rounded-tl-none bg-[var(--surface-strong)] border border-[var(--line-strong)] text-xs text-[var(--muted)] flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[var(--brand)] animate-ping" />
                  <span>Consulting DBARS deterministic engine &amp; knowledge base...</span>
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Chat Input Bar */}
          <div className="p-3 border-t border-[var(--line)] bg-[var(--surface-strong)]">
            <form
              onSubmit={(e: FormEvent) => {
                e.preventDefault();
                handleSend();
              }}
              className="flex items-center gap-2"
            >
              <div className="relative flex-1">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={currentModeConfig.placeholder}
                  disabled={loading}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-[var(--line-strong)] bg-[var(--bg)] text-xs text-[var(--text)] placeholder-[var(--muted)] focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)] transition-all"
                />
              </div>

              <button
                type="submit"
                disabled={loading || !input.trim()}
                className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-[var(--brand)] to-[var(--brand-2)] text-white font-bold text-xs flex items-center gap-1.5 shadow-md hover:opacity-95 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
              >
                <span>Ask</span>
                <Send size={14} />
              </button>
            </form>

            <div className="flex items-center justify-between text-[10px] text-[var(--muted)] mt-2 px-1">
              <span>Shortcuts: Press Enter to send • Alt+A to toggle</span>
              <span className="flex items-center gap-1">
                <ShieldCheck size={11} className="text-[var(--brand)]" />
                PII-sanitized memory active
              </span>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
