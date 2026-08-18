import { FormEvent, useState } from "react";
import { motion } from "framer-motion";
import { ArrowRightLeft, Loader2, Search, Sparkles } from "lucide-react";
import { api } from "../services/api";
import type { PredictionResponse } from "../types/api";
import { AutocompleteInput } from "./AutocompleteInput";
import { VoiceButton } from "./VoiceButton";

type Props = {
  onResult: (result: PredictionResponse) => void;
  onHistory: (item: string) => void;
};

export function SearchPanel({ onResult, onHistory }: Props) {
  const [currentStop, setCurrentStop] = useState("Silk Board");
  const [destination, setDestination] = useState("Marathahalli");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const plan = await api.planRoute(currentStop, destination, 7);
      setCurrentStop(plan.currentStop);
      setDestination(plan.destination);
      onResult(plan.result);
      onHistory(`${plan.currentStop} -> ${plan.destination}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Prediction failed");
    } finally {
      setLoading(false);
    }
  };

  const swap = () => {
    setCurrentStop(destination);
    setDestination(currentStop);
  };

  return (
    <motion.form
      onSubmit={submit}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: [0.34, 1.56, 0.64, 1] }}
      className="search-panel"
      id="search-form"
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="eyebrow">
            <Sparkles size={12} /> Hybrid ML · Route Intelligence
          </p>
          <h2 className="panel-title">Find the best bus</h2>
        </div>
        <VoiceButton
          onTranscript={(value) => {
            if (!value) {
              setError("Voice input is not available in this browser.");
              return;
            }
            const parts = value.split(/\s+towards\s+|\s+to\s+/i);
            if (parts.length >= 2) {
              setCurrentStop(parts[0]);
              setDestination(parts.slice(1).join(" "));
            } else {
              setCurrentStop(value);
            }
          }}
        />
      </div>

      {/* From */}
      <AutocompleteInput
        label="Current stop"
        value={currentStop}
        kind="stop"
        placeholder="Kempegowda Bus Station"
        onChange={setCurrentStop}
      />

      {/* Swap */}
      <div className="flex justify-center">
        <button
          type="button"
          onClick={swap}
          className="icon-button"
          title="Swap stops"
          aria-label="Swap stops"
        >
          <ArrowRightLeft size={17} />
        </button>
      </div>

      {/* To */}
      <AutocompleteInput
        label="Destination bus stop"
        value={destination}
        kind="stop"
        placeholder="Marathahalli"
        onChange={setDestination}
      />

      {error && <p className="error-text">{error}</p>}

      <button type="submit" className="primary-button" disabled={loading} id="predict-btn">
        {loading ? (
          <Loader2 className="animate-spin" size={18} />
        ) : (
          <Search size={18} />
        )}
        <span>{loading ? "Finding routes…" : "Predict bus"}</span>
      </button>
    </motion.form>
  );
}
