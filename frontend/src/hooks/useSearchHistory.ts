import { useState, useEffect, useCallback } from "react";

export function useSearchHistory(storageKey: string, maxItems: number = 5) {
  const [history, setHistory] = useState<string[]>([]);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          setHistory(parsed);
        } else {
          localStorage.removeItem(storageKey);
        }
      }
    } catch (err) {
      console.warn("Couldn't read search history from local storage, wiping it cleanly", err);
      try { localStorage.removeItem(storageKey); } catch {}
    }
  }, [storageKey]);

  const addHistory = useCallback((term: string) => {
    if (!term || !term.trim()) return;
    const cleanTerm = term.trim();
    
    setHistory(prev => {
      const filtered = prev.filter(item => item.toLowerCase() !== cleanTerm.toLowerCase());
      const newHistory = [cleanTerm, ...filtered].slice(0, maxItems);
      
      try {
        localStorage.setItem(storageKey, JSON.stringify(newHistory));
      } catch (err) {
        console.warn("Local storage is full or disabled, history won't save across reloads", err);
      }
      return newHistory;
    });
  }, [storageKey, maxItems]);

  const removeHistory = useCallback((term: string) => {
    setHistory(prev => {
      const newHistory = prev.filter(item => item !== term);
      try {
        localStorage.setItem(storageKey, JSON.stringify(newHistory));
      } catch (err) {
        console.error("Failed to save search history", err);
      }
      return newHistory;
    });
  }, [storageKey]);

  const clearHistory = useCallback(() => {
    setHistory([]);
    try {
      localStorage.removeItem(storageKey);
    } catch (err) {
      console.error("Failed to clear search history", err);
    }
  }, [storageKey]);

  return { history, addHistory, removeHistory, clearHistory };
}
