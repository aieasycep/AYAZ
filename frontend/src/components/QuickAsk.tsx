'use client';

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  KeyboardEvent,
} from 'react';
import { useRouter } from 'next/navigation';
import { createConversationWithMessage } from '@/lib/assistant-api';
import styles from './QuickAsk.module.css';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface QuickAskProps {
  /** Called when the user dismisses the modal (Esc or backdrop click). */
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function QuickAsk({ onClose }: QuickAskProps) {
  const router = useRouter();

  const [value, setValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  /** Track the element focused before the modal opened so we can restore it. */
  const previousFocusRef = useRef<Element | null>(null);

  // ---- Save previous focus + autofocus input when mounted ----
  useEffect(() => {
    previousFocusRef.current = document.activeElement;
    const timer = setTimeout(() => {
      inputRef.current?.focus();
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  // ---- Close helper ----
  const handleClose = useCallback(() => {
    if (loading) return; // don't close mid-request
    onClose();
    if (
      previousFocusRef.current &&
      typeof (previousFocusRef.current as HTMLElement).focus === 'function'
    ) {
      (previousFocusRef.current as HTMLElement).focus();
    }
  }, [loading, onClose]);

  // ---- Esc key to close (global listener) ----
  useEffect(() => {
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault();
        handleClose();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [handleClose]);

  // ---- Focus trap: keep Tab inside the dialog ----
  function handleDialogKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== 'Tab') return;
    if (!dialogRef.current) return;

    const focusable = Array.from(
      dialogRef.current.querySelectorAll<HTMLElement>(
        'input, button, [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => !el.hasAttribute('disabled'));

    if (focusable.length === 0) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  // ---- Submit ----
  async function handleSubmit() {
    const trimmed = value.trim();
    if (!trimmed || loading) return;

    setError(null);
    setLoading(true);

    try {
      const conv = await createConversationWithMessage(trimmed);
      // Navigate to the assistant page and select the new conversation
      router.push(`/assistant?c=${conv.id}`);
      onClose();
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : 'Sohbet başlatılamadı. Lütfen tekrar deneyin.',
      );
      setLoading(false);
    }
  }

  function handleInputKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  }

  // ---- Render ----
  return (
    // Backdrop
    <div
      className={styles.backdrop}
      onClick={handleClose}
      aria-hidden="true"
    >
      {/* Dialog — stop propagation so backdrop click doesn't close when clicking inside */}
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="Veriye Sor"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={handleDialogKeyDown}
      >
        {/* Header */}
        <div className={styles.header}>
          {/* Spark icon */}
          <svg
            className={styles.headerIcon}
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
          <span className={styles.headerTitle}>Veriye Sor</span>
          <button
            className={styles.closeBtn}
            onClick={handleClose}
            aria-label="Kapat"
            disabled={loading}
            type="button"
          >
            <svg
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
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Input row */}
        <div className={styles.inputRow}>
          <input
            ref={inputRef}
            className={styles.input}
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="örn. 'son 30 günde en iyi ROAS hangi kanal?'"
            aria-label="Sorunuzu yazın"
            disabled={loading}
            autoComplete="off"
            spellCheck={false}
          />
          <button
            className={styles.submitBtn}
            onClick={handleSubmit}
            disabled={!value.trim() || loading}
            aria-label="Soruyu gönder"
            type="button"
          >
            {loading ? (
              <span className={styles.spinner} aria-label="Gönderiliyor" />
            ) : (
              'Sor'
            )}
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        {/* Hint */}
        {!error && (
          <div className={styles.hint}>
            <kbd className={styles.kbd}>Enter</kbd>
            ile gönder &nbsp;·&nbsp;
            <kbd className={styles.kbd}>Esc</kbd>
            ile kapat
          </div>
        )}
      </div>
    </div>
  );
}
