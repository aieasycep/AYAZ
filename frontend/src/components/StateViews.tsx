import React from 'react';
import styles from './StateViews.module.css';

// ---------------------------------------------------------------------------
// LoadingState
// ---------------------------------------------------------------------------

interface LoadingStateProps {
  /** Optional message shown beneath the spinner. */
  message?: string;
}

export function LoadingState({ message }: LoadingStateProps) {
  return (
    <div className={styles.stateBox}>
      <span
        className={styles.spinner}
        role="status"
        aria-label={message ?? 'Yükleniyor'}
      />
      {message && <span className={styles.stateMessage}>{message}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ErrorState
// ---------------------------------------------------------------------------

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className={`${styles.stateBox} ${styles.stateBoxError}`} role="alert">
      <span className={styles.errorIcon} aria-hidden="true">!</span>
      <span className={styles.stateMessage}>{message}</span>
      {onRetry && (
        <button className={styles.retryBtn} onClick={onRetry}>
          Tekrar dene
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

interface EmptyStateProps {
  /** Large decorative character or short text (e.g. an emoji if desired). */
  icon?: React.ReactNode;
  title: string;
  description?: string;
  /** Optional call-to-action element (e.g. a <Link> or <button>). */
  cta?: React.ReactNode;
}

export function EmptyState({ icon, title, description, cta }: EmptyStateProps) {
  return (
    <div className={styles.emptyBox}>
      {icon && <span className={styles.emptyIcon} aria-hidden="true">{icon}</span>}
      <span className={styles.emptyTitle}>{title}</span>
      {description && (
        <span className={styles.emptyDesc}>{description}</span>
      )}
      {cta && <div className={styles.emptyCta}>{cta}</div>}
    </div>
  );
}
