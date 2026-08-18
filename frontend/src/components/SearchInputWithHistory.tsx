import { useEffect, useRef, useState } from "react";
import { Search, Clock, X } from "lucide-react";
import { useSearchHistory } from "../hooks/useSearchHistory";
import { useLanguage } from "../contexts/LanguageContext";

type Props = {
  storageKey: string;
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  className?: string;
  onSubmit?: () => void;
};

export function SearchInputWithHistory({
  storageKey,
  value,
  onChange,
  placeholder = "Search...",
  className = "",
  onSubmit,
}: Props) {
  const { history, addHistory, removeHistory, clearHistory } = useSearchHistory(storageKey);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { t } = useLanguage();

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      setOpen(false);
      if (value.trim()) addHistory(value.trim());
      onSubmit?.();
    }
    if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const clearValue = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onChange("");
    setOpen(false);
    setTimeout(() => inputRef.current?.focus(), 50);
  };

  return (
    <div className={`relative ${className}`} ref={wrapperRef} style={{ width: '100%' }}>
      <div className="relative flex items-center" style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
        <Search className="input-icon" size={17} style={{ position: 'absolute', left: '12px', color: 'var(--text-muted)', pointerEvents: 'none', zIndex: 1 }} />
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          className="smart-input"
          style={{ paddingLeft: '40px', paddingRight: value ? '36px' : '14px', width: '100%', boxSizing: 'border-box' }}
          placeholder={placeholder}
          autoComplete="off"
        />
        {/* Clear button */}
        {value && (
          <button
            type="button"
            onMouseDown={clearValue}
            tabIndex={-1}
            aria-label="Clear search"
            style={{
              position: 'absolute', right: '10px',
              background: 'none', border: 'none', cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              padding: '4px', borderRadius: '50%',
              color: 'var(--text-muted)', zIndex: 2, transition: 'color 0.15s'
            }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-muted)')}
          >
            <X size={15} />
          </button>
        )}
      </div>

      {open && history.length > 0 && (
        <div className="suggestion-menu" style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50 }}>
          <div style={{ padding: '8px 12px', fontSize: '0.8rem', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
            <span>Recent Searches</span>
            <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); clearHistory(); }} style={{ background: 'none', border: 'none', color: 'var(--brand)', cursor: 'pointer', fontSize: '0.8rem' }}>
              Clear All
            </button>
          </div>
          {history.map((item) => (
            <button
              key={item}
              type="button"
              className="suggestion-item"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}
              onMouseDown={(e) => {
                e.preventDefault(); // Prevents input onBlur which might close the menu too fast
                onChange(item);
                addHistory(item); // bump to top
                setOpen(false);
                if (onSubmit) {
                  // Slight delay to allow state update before submitting
                  setTimeout(onSubmit, 0);
                }
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Clock size={14} className="text-muted" />
                <span>{item}</span>
              </div>
              <span 
                className="delete-history-btn" 
                style={{ cursor: 'pointer', opacity: 0.5 }} 
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
    </div>
  );
}
