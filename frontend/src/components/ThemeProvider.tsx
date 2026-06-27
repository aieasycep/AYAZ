'use client';

import { createContext, useContext, useEffect, useState, useCallback } from 'react';

export type ThemeValue = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'ayaz_theme';
const DEFAULT_THEME: ThemeValue = 'system';

// ── helpers ──────────────────────────────────────────────────────────────────

function readStoredTheme(): ThemeValue {
  if (typeof window === 'undefined') return DEFAULT_THEME;
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  return DEFAULT_THEME;
}

function applyTheme(theme: ThemeValue) {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.theme = theme;
}

// ── context ───────────────────────────────────────────────────────────────────

interface ThemeContextValue {
  theme: ThemeValue;
  setTheme: (t: ThemeValue) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: DEFAULT_THEME,
  setTheme: () => undefined,
});

export function useTheme() {
  return useContext(ThemeContext);
}

// ── provider ──────────────────────────────────────────────────────────────────

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeValue>(DEFAULT_THEME);

  // On mount: read persisted preference and sync to DOM
  useEffect(() => {
    const stored = readStoredTheme();
    setThemeState(stored);
    applyTheme(stored);
  }, []);

  // When theme === 'system', track OS preference changes in real time
  useEffect(() => {
    if (theme !== 'system') return;
    // The CSS already handles the visual switch via @media prefers-color-scheme
    // when data-theme="system". We just need to keep data-theme in sync.
    applyTheme('system');
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => {
      // Re-applying 'system' is a no-op for the DOM attribute, but it
      // ensures any imperative callers that read the resolved value are current.
      applyTheme('system');
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [theme]);

  const setTheme = useCallback((t: ThemeValue) => {
    setThemeState(t);
    localStorage.setItem(STORAGE_KEY, t);
    applyTheme(t);
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
