import { useEffect, useRef, useState } from "react";
import { MapPin, Clock, X } from "lucide-react";
import { api } from "../services/api";
import type { AutocompleteItem } from "../types/api";
import { useSearchHistory } from "../hooks/useSearchHistory";

type Props = {
  label: string;
  value: string;
  kind: "stop" | "destination";
  placeholder: string;
  onChange: (value: string) => void;
};

export function AutocompleteInput({ label, value, kind, placeholder, onChange }: Props) {
  const [items, setItems] = useState<AutocompleteItem[]>([]);
  const [open, setOpen] = useState(false);
  const { history, addHistory, removeHistory, clearHistory } = useSearchHistory(`bmtc_history_${kind}`);
  const timer = useRef<number | null>(null);
  const wrapperRef = useRef<HTMLLabelElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Close the dropdown if the user clicks anywhere else on the page
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    let active = true;
    if (timer.current) window.clearTimeout(timer.current);
    if (value.trim().length < 2) {
      setItems([]);
      return;
    }
    // debounce the API calls so we don't spam the backend on every keystroke
    timer.current = window.setTimeout(() => {
      api
        .autocomplete(value, kind)
        .then((response) => {
          if (active) {
            setItems(response.items);
            setOpen(true);
          }
        })
        .catch(() => {
          if (active) setItems([]);
        });
    }, 160);
    return () => {
      active = false;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [value, kind]);

  // Select a suggestion — use onMouseDown so it fires BEFORE the input's onBlur
  // closes the dropdown. This makes it work reliably on first tap (mobile) too.
  const selectItem = (val: string) => {
    onChange(val);
    addHistory(val);
    setOpen(false);
    inputRef.current?.blur();
  };

  const clearValue = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onChange("");
    setItems([]);
    setOpen(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  return (
    <label className="input-shell" ref={wrapperRef} style={{ position: 'relative' }}>
      <span className="input-label">{label}</span>
      <span className="relative flex items-center" style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
        <MapPin className="input-icon" size={17} style={{ position: 'absolute', left: '14px', zIndex: 1, pointerEvents: 'none', color: 'var(--brand)' }} />
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && value.trim()) {
              addHistory(value.trim());
              setOpen(false);
            }
            if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          className="smart-input"
          style={{ paddingLeft: '44px', paddingRight: value ? '36px' : '14px' }}
          placeholder={placeholder}
          autoComplete="off"
        />
        {/* Clear button — only shown when there's text */}
        {value && (
          <button
            type="button"
            onMouseDown={clearValue}
            tabIndex={-1}
            aria-label="Clear input"
            style={{
              position: 'absolute',
              right: '10px',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '4px',
              borderRadius: '50%',
              color: 'var(--text-muted)',
              zIndex: 2,
              transition: 'color 0.15s, background 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-muted)')}
          >
            <X size={15} />
          </button>
        )}
      </span>

      {/* Autocomplete suggestions */}
      {open && items.length > 0 && value.trim().length >= 2 && (
        <div className="suggestion-menu" role="listbox">
          {items.map((item) => (
            <button
              key={item.value}
              type="button"
              role="option"
              onMouseDown={(e) => {
                e.preventDefault(); // prevent input blur before selection
                selectItem(item.value);
              }}
              className="suggestion-item"
            >
              <span>{item.value}</span>
              <span className="score-badge">{Math.round(item.score * 100)}%</span>
            </button>
          ))}
        </div>
      )}

      {/* Recent history dropdown */}
      {open && value.trim().length < 2 && history.length > 0 && (
        <div className="suggestion-menu" role="listbox">
          <div style={{ padding: '8px 12px', fontSize: '0.8rem', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Recent {kind === "stop" ? "Stops" : "Destinations"}</span>
            <button
              type="button"
              onMouseDown={(e) => { e.preventDefault(); clearHistory(); }}
              style={{ background: 'none', border: 'none', color: 'var(--brand)', cursor: 'pointer', fontSize: '0.8rem' }}
            >
              Clear All
            </button>
          </div>
          {history.map((item) => (
            <button
              key={item}
              type="button"
              role="option"
              onMouseDown={(e) => {
                e.preventDefault();
                selectItem(item);
              }}
              className="suggestion-item"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Clock size={14} className="text-muted" />
                <span>{item}</span>
              </div>
              <span
                style={{ cursor: 'pointer', opacity: 0.5, padding: '2px 4px' }}
                onMouseDown={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  removeHistory(item);
                }}
              >
                <X size={14} />
              </span>
            </button>
          ))}
        </div>
      )}
    </label>
  );
}
