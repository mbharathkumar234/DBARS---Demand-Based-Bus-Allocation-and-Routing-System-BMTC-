import { Mic, MicOff } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLanguage, type Language } from "../contexts/LanguageContext";

type Props = {
  onTranscript: (value: string) => void;
  /** Called with a message the user can act on. Optional; without it, failures
   *  are silent, which is why PredictPage passes one. */
  onError?: (message: string) => void;
};

type RecognitionErrorEvent = { error: string };

type SpeechRecognitionInstance = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionInstance;

type SpeechWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

function getRecognition(): SpeechRecognitionConstructor | undefined {
  const w = window as SpeechWindow;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

// The app ships four languages; recognition was previously pinned to en-IN
// regardless, so a Kannada speaker got their stop name transcribed as English.
const RECOGNITION_LANG: Record<Language, string> = {
  en: "en-IN",
  kn: "kn-IN",
  hi: "hi-IN",
  te: "te-IN",
};

// Spoken back to the user, so each one says what to actually do about it.
function messageForError(code: string): string {
  switch (code) {
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access was blocked. Allow it in your browser's site settings to search by voice.";
    case "no-speech":
      return "Didn't catch anything. Tap the mic and say, for example, \"Silk Board to Marathahalli\".";
    case "audio-capture":
      return "No microphone found. Check that one is connected and not in use by another app.";
    case "network":
      return "Voice recognition needs a network connection and couldn't reach the service.";
    case "aborted":
      return "";
    default:
      return "Voice input failed. Please type the stop names instead.";
  }
}

export function VoiceButton({ onTranscript, onError }: Props) {
  const { lang } = useLanguage();
  const [listening, setListening] = useState(false);
  const recognizerRef = useRef<SpeechRecognitionInstance | null>(null);

  // Resolved once: browsers that lack the API never gain it at runtime, and
  // this decides whether the control renders at all.
  const [supported] = useState(() => Boolean(getRecognition()));

  // A recognizer left running past unmount keeps the microphone indicator lit.
  useEffect(() => {
    return () => {
      recognizerRef.current?.abort();
      recognizerRef.current = null;
    };
  }, []);

  const stop = () => {
    recognizerRef.current?.stop();
    setListening(false);
  };

  const start = () => {
    const SpeechRecognition = getRecognition();
    if (!SpeechRecognition) {
      // Unreachable while `supported` gates rendering, but the API contract
      // shouldn't depend on that staying true.
      onError?.("Voice search isn't available on this device.");
      return;
    }

    const recognizer = new SpeechRecognition();
    recognizerRef.current = recognizer;
    recognizer.continuous = false;
    recognizer.interimResults = false;
    recognizer.lang = RECOGNITION_LANG[lang] ?? "en-IN";

    recognizer.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript?.trim();
      // Only ever fires with a real transcript. The previous version signalled
      // "unsupported" by calling this with "", which every caller then had to
      // know to special-case.
      if (transcript) {
        onTranscript(transcript);
      } else {
        onError?.("Didn't catch that. Please try again.");
      }
    };

    recognizer.onerror = (event) => {
      const message = messageForError(event.error);
      if (message) onError?.(message);
      setListening(false);
    };

    recognizer.onend = () => {
      setListening(false);
      recognizerRef.current = null;
    };

    setListening(true);
    try {
      recognizer.start();
    } catch {
      // start() throws if a recognition session is already running.
      setListening(false);
    }
  };

  // Rendering a mic that cannot work is worse than rendering nothing: on an
  // Android WebView build (the Capacitor APK) the Web Speech API is absent, and
  // a dead button reads as a broken app rather than an unavailable feature.
  if (!supported) return null;

  return (
    <button
      type="button"
      className={`voice-btn${listening ? " recording" : ""}`}
      onClick={listening ? stop : start}
      title={listening ? "Stop listening" : "Search by voice"}
      aria-label={listening ? "Stop listening" : "Search by voice"}
      aria-pressed={listening}
    >
      {listening ? <MicOff size={18} /> : <Mic size={18} />}
    </button>
  );
}
