'use client';

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  KeyboardEvent as ReactKeyboardEvent,
} from 'react';
import { useRouter } from 'next/navigation';
import { logout as logoutApi } from '@/lib/api';
import { useTheme, type ThemeValue } from './ThemeProvider';
import { NAV_LINKS } from './AppNav';
import styles from './CommandPalette.module.css';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ItemKind = 'nav' | 'action';

interface NavItem {
  kind: 'nav';
  id: string;
  label: string;
  href: string;
}

interface ActionItem {
  kind: 'action';
  id: string;
  label: string;
  run: () => void | Promise<void>;
}

type PaletteItem = NavItem | ActionItem;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Normalize a string for diacritic-insensitive, case-insensitive matching.
 * Falls back to simple toLowerCase if normalize is unavailable (very old envs).
 */
function normalize(str: string): string {
  try {
    return str
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase();
  } catch {
    return str.toLowerCase();
  }
}

function matches(item: PaletteItem, query: string): boolean {
  if (!query) return true;
  return normalize(item.label).includes(normalize(query));
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CommandPaletteProps {
  /** Called when the user selects "Veriye Sor" from the palette. */
  onOpenQuickAsk?: () => void;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CommandPalette({ onOpenQuickAsk }: CommandPaletteProps) {
  const router = useRouter();
  const { theme, setTheme } = useTheme();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const previousFocusRef = useRef<Element | null>(null);

  // ---------------------------------------------------------------------------
  // Build items list — navigation items + quick actions
  // ---------------------------------------------------------------------------

  // Extra pages accessible via the palette but not in the top-nav bar
  const EXTRA_PALETTE_LINKS = [
    { href: '/notifications', label: 'Bildirimler' },
  ];

  const navItems: NavItem[] = [...NAV_LINKS, ...EXTRA_PALETTE_LINKS].map((link) => ({
    kind: 'nav',
    id: `nav:${link.href}`,
    label: link.label,
    href: link.href,
  }));

  function buildActions(): ActionItem[] {
    const nextTheme: ThemeValue =
      theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light';
    const themeLabel =
      theme === 'light'
        ? 'Koyu temaya geç'
        : theme === 'dark'
        ? 'Sistem temasına geç'
        : 'Açık temaya geç';

    const actions: ActionItem[] = [
      {
        kind: 'action',
        id: 'action:veriye-sor',
        label: 'Veriye Sor',
        run: () => {
          if (onOpenQuickAsk) onOpenQuickAsk();
        },
      },
      {
        kind: 'action',
        id: 'action:theme',
        label: themeLabel,
        run: () => setTheme(nextTheme),
      },
      {
        kind: 'action',
        id: 'action:logout',
        label: 'Oturumu kapat',
        run: async () => {
          await logoutApi();
          router.push('/login');
        },
      },
    ];

    return actions;
  }

  const allItems: PaletteItem[] = [...navItems, ...buildActions()];
  const filtered = allItems.filter((item) => matches(item, query));

  // ---------------------------------------------------------------------------
  // Open / close
  // ---------------------------------------------------------------------------

  const openPalette = useCallback(() => {
    previousFocusRef.current = document.activeElement;
    setQuery('');
    setActiveIndex(0);
    setOpen(true);
  }, []);

  const closePalette = useCallback(() => {
    setOpen(false);
    // Restore focus to previously focused element
    if (
      previousFocusRef.current &&
      typeof (previousFocusRef.current as HTMLElement).focus === 'function'
    ) {
      (previousFocusRef.current as HTMLElement).focus();
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Global ⌘K / Ctrl+K listener
  // ---------------------------------------------------------------------------

  useEffect(() => {
    function handleGlobalKeyDown(e: globalThis.KeyboardEvent) {
      // Always allow ⌘K/Ctrl+K regardless of focused element
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (open) {
          closePalette();
        } else {
          openPalette();
        }
        return;
      }
    }

    document.addEventListener('keydown', handleGlobalKeyDown);
    return () => document.removeEventListener('keydown', handleGlobalKeyDown);
  }, [open, openPalette, closePalette]);

  // ---------------------------------------------------------------------------
  // Autofocus input when palette opens
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (open) {
      // Next tick to let the DOM render first
      const timer = setTimeout(() => {
        inputRef.current?.focus();
      }, 0);
      return () => clearTimeout(timer);
    }
  }, [open]);

  // ---------------------------------------------------------------------------
  // Reset active index when filtered list changes
  // ---------------------------------------------------------------------------

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  // ---------------------------------------------------------------------------
  // Scroll active item into view
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!listRef.current) return;
    const activeEl = listRef.current.querySelector<HTMLLIElement>(
      `[data-index="${activeIndex}"]`,
    );
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  // ---------------------------------------------------------------------------
  // Keyboard navigation inside the palette
  // ---------------------------------------------------------------------------

  function handleInputKeyDown(e: ReactKeyboardEvent<HTMLInputElement>) {
    switch (e.key) {
      case 'Escape':
        e.preventDefault();
        closePalette();
        break;

      case 'ArrowDown':
        e.preventDefault();
        setActiveIndex((prev) =>
          filtered.length === 0 ? 0 : (prev + 1) % filtered.length,
        );
        break;

      case 'ArrowUp':
        e.preventDefault();
        setActiveIndex((prev) =>
          filtered.length === 0
            ? 0
            : (prev - 1 + filtered.length) % filtered.length,
        );
        break;

      case 'Enter':
        e.preventDefault();
        if (filtered[activeIndex]) {
          activateItem(filtered[activeIndex]);
        }
        break;

      default:
        break;
    }
  }

  // ---------------------------------------------------------------------------
  // Activate an item
  // ---------------------------------------------------------------------------

  function activateItem(item: PaletteItem) {
    closePalette();
    if (item.kind === 'nav') {
      router.push(item.href);
    } else {
      // Run async actions; errors are intentionally unhandled here (best-effort)
      void item.run();
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (!open) return null;

  return (
    // Backdrop — click outside closes
    <div
      className={styles.backdrop}
      onClick={closePalette}
      aria-hidden="true"
    >
      {/* Dialog — stop propagation so clicks inside don't close */}
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="Komut paleti"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div className={styles.inputRow}>
          {/* Search icon */}
          <svg
            className={styles.searchIcon}
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>

          <input
            ref={inputRef}
            className={styles.input}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Sayfa ara veya komut çalıştır…"
            aria-label="Komut paleti araması"
            aria-autocomplete="list"
            aria-controls="cmd-palette-listbox"
            aria-activedescendant={
              filtered[activeIndex]
                ? `cmd-item-${filtered[activeIndex].id}`
                : undefined
            }
            autoComplete="off"
            spellCheck={false}
          />

          <kbd className={styles.escHint}>Esc</kbd>
        </div>

        {/* Results list */}
        <ul
          id="cmd-palette-listbox"
          ref={listRef}
          className={styles.list}
          role="listbox"
          aria-label="Sonuçlar"
        >
          {filtered.length === 0 && (
            <li className={styles.empty} role="option" aria-selected={false}>
              Sonuç bulunamadı
            </li>
          )}

          {filtered.map((item, idx) => (
            <li
              key={item.id}
              id={`cmd-item-${item.id}`}
              data-index={idx}
              className={`${styles.item} ${idx === activeIndex ? styles.itemActive : ''}`}
              role="option"
              aria-selected={idx === activeIndex}
              onMouseEnter={() => setActiveIndex(idx)}
              onClick={() => activateItem(item)}
            >
              {/* Item label */}
              <span className={styles.itemLabel}>{item.label}</span>

              {/* Tag badge */}
              <span
                className={`${styles.tag} ${
                  item.kind === 'action' ? styles.tagAction : styles.tagNav
                }`}
              >
                {item.kind === 'action' ? 'Komut' : 'Sayfa'}
              </span>
            </li>
          ))}
        </ul>

        {/* Footer hint */}
        <div className={styles.footer}>
          <span className={styles.footerHint}>
            <kbd className={styles.kbd}>↑</kbd>
            <kbd className={styles.kbd}>↓</kbd>
            gezin
          </span>
          <span className={styles.footerHint}>
            <kbd className={styles.kbd}>↵</kbd>
            seç
          </span>
          <span className={styles.footerHint}>
            <kbd className={styles.kbd}>Esc</kbd>
            kapat
          </span>
        </div>
      </div>
    </div>
  );
}
