import { FormEvent, useEffect, useRef, useState } from "react";
import { Bot, Loader2, Send, Sparkles, Zap } from "lucide-react";
import { api } from "../services/api";
import type { PredictionResponse } from "../types/api";

type Message = {
  role: "user" | "assistant" | "thinking";
  text: string;
  result?: PredictionResponse;
};

type Props = {
  onResult: (result: PredictionResponse) => void;
  onHistory: (item: string) => void;
};

/**
 * Split a free-text query like "Majestic to Whitefield" into [source, destination].
 * Returns ALL possible split positions — the same strategy the main SearchPanel uses.
 * We pass ALL splits to api.planRoute() (which has the same candidate-expansion logic
 * as the main search) and pick the result that yields a best_match.
 */
function extractStopCandidatePairs(text: string): Array<[string, string]> {
  const tokens = text.trim().split(/\s+/);
  const separators = new Set(["to", "towards", "->", "→", "for"]);
  const pairs: Array<[string, string]> = [];

  for (let i = 1; i < tokens.length; i++) {
    if (separators.has(tokens[i].toLowerCase())) {
      const left = tokens.slice(0, i).join(" ").trim();
      const right = tokens.slice(i + 1).join(" ").trim();
      if (left && right) {
        pairs.push([left, right]);
      }
    }
  }

  // Fallback: split on comma
  if (pairs.length === 0) {
    const commaParts = text.split(",").map((s) => s.trim()).filter(Boolean);
    if (commaParts.length >= 2) {
      pairs.push([commaParts[0], commaParts.slice(1).join(", ")]);
    }
  }

  // Last resort: half/half
  if (pairs.length === 0 && tokens.length >= 2) {
    const mid = Math.floor(tokens.length / 2);
    pairs.push([tokens.slice(0, mid).join(" "), tokens.slice(mid).join(" ")]);
  }

  return pairs;
}

export function AssistantPanel({ onResult, onHistory }: Props) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      text: "Hi! Ask me any route question — e.g. \"Majestic to Whitefield\" or \"Silk Board to Marathahalli\".",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setLoading(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", text },
      { role: "thinking", text: "" },
    ]);

    try {
      const candidatePairs = extractStopCandidatePairs(text);

      if (candidatePairs.length === 0) {
        setMessages((prev) => [
          ...prev.filter((m) => m.role !== "thinking"),
          {
            role: "assistant",
            text: 'Please include both a current stop and a destination — e.g. "Majestic to Whitefield".',
          },
        ]);
        return;
      }

      // Try each split using api.planRoute() — the SAME logic the main SearchPanel
      // uses (with candidate expansion, stopCandidates, etc.).  This guarantees that
      // for any given source+destination the copilot returns the same predictions.
      let bestPlan = null;
      for (const [rawSource, rawDest] of candidatePairs) {
        const plan = await api.planRoute(rawSource, rawDest, 7);
        if (plan.result.best_match) {
          bestPlan = plan;
          break;
        }
        if (!bestPlan) {
          bestPlan = plan;
        } else if (
          !bestPlan.result.best_match &&
          (plan.result.best_match || plan.result.alternatives?.length)
        ) {
          bestPlan = plan;
        }
      }

      if (!bestPlan) throw new Error("Could not parse a stop pair from your query.");

      onResult(bestPlan.result);
      onHistory(`${bestPlan.currentStop} -> ${bestPlan.destination}`);

      const best = bestPlan.result.best_match;
      const hasSteps = bestPlan.result.alternatives && bestPlan.result.alternatives.length > 0 && bestPlan.result.alternatives[0].transfers > 0;
      const resolvedNote =
        bestPlan.currentStop.toLowerCase() !== candidatePairs[0][0].toLowerCase() ||
        bestPlan.destination.toLowerCase() !== candidatePairs[0][1].toLowerCase()
          ? ` (resolved: "${bestPlan.currentStop}" → "${bestPlan.destination}")`
          : "";

      let replyText = "";
      if (best) {
        replyText = `🚌 Take **${best.bus_number}**${resolvedNote}. Confidence: **${best.confidence}%**.\nRoute: ${best.source} → ${best.destination}.\nSpan: ${best.stop_span} stops.`;
      } else if (hasSteps) {
        const alt = bestPlan.result.alternatives[0];
        replyText = `🔄 No direct bus${resolvedNote}. Recommended transfer:\n` + alt.legs.map((s: any, i: number) => `${i + 1}. Board ${s.bus_number} from ${s.from_stop} to ${s.to_stop}`).join("\n");
      } else {
        replyText = `${bestPlan.result.message ?? "No direct or transfer route was found for those stops."}${resolvedNote}`;
      }

      setMessages((prev) => [
        ...prev.filter((m) => m.role !== "thinking"),
        { role: "assistant", text: replyText, result: bestPlan.result },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev.filter((m) => m.role !== "thinking"),
        {
          role: "assistant",
          text: error instanceof Error ? error.message : "I could not answer that. Please try again.",
        },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const renderText = (text: string) => {
    // Simple bold **text** rendering
    const parts = text.split(/(\*\*[^*]+\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i}>{part.slice(2, -2)}</strong>;
      }
      return part.split("\n").map((line, j) =>
        j === 0 ? line : [<br key={`${i}-br-${j}`} />, line]
      );
    });
  };

  return (
    <section className="copilot-panel">
      <div className="copilot-header">
        <div className="copilot-header-icon">
          <Bot size={18} />
        </div>
        <div>
          <p className="eyebrow">
            <Zap size={12} /> AI Assistant
          </p>
          <h2 className="panel-title">Route Copilot</h2>
        </div>
        <div className="copilot-badge">
          <Sparkles size={13} />
          <span>Live</span>
        </div>
      </div>

      <div className="copilot-chat-log" id="copilot-chat-log">
        {messages.map((message, index) => {
          if (message.role === "thinking") {
            return (
              <div key={`thinking-${index}`} className="chat-bubble assistant thinking-bubble">
                <span className="dot" />
                <span className="dot" />
                <span className="dot" />
              </div>
            );
          }
          return (
            <div
              key={`${message.role}-${index}`}
              className={`chat-bubble ${message.role}`}
            >
              {renderText(message.text)}
            </div>
          );
        })}
        <div ref={chatEndRef} />
      </div>

      <form onSubmit={submit} className="copilot-form">
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. Majestic to Whitefield"
          disabled={loading}
          id="copilot-input"
          autoComplete="off"
        />
        <button
          type="submit"
          className="copilot-send-btn"
          aria-label="Send message"
          disabled={loading || !input.trim()}
        >
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </form>
    </section>
  );
}
