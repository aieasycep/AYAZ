'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  getNotifications,
  getUnreadCount,
  markRead,
  markAllRead,
  type NotificationOut,
  type NotificationSeverity,
} from '@/lib/notifications-api';
import { LoadingState, ErrorState, EmptyState } from './StateViews';
import styles from './NotificationBell.module.css';

// ---------------------------------------------------------------------------
// Relative-time helper (Turkish)
// ---------------------------------------------------------------------------

function formatRelativeTr(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const diffMs = now - then;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);

  if (diffSec < 60) return 'az önce';
  if (diffMin < 60) return `${diffMin} dakika önce`;
  if (diffHour < 24) return `${diffHour} saat önce`;
  if (diffHour < 48) return 'dün';

  const d = new Date(iso);
  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const year = d.getFullYear();
  return `${day}.${month}.${year}`;
}

// ---------------------------------------------------------------------------
// Severity stripe class helper
// ---------------------------------------------------------------------------

function severityClass(severity: NotificationSeverity): string {
  switch (severity) {
    case 'critical':
      return styles.severityStripeCritical;
    case 'warning':
      return styles.severityStripeWarning;
    default:
      return styles.severityStripeInfo;
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type PanelState = 'idle' | 'loading' | 'error' | 'done';

export default function NotificationBell() {
  const router = useRouter();
  const wrapperRef = useRef<HTMLDivElement>(null);

  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const [panelState, setPanelState] = useState<PanelState>('idle');

  // ---- Poll unread count ----

  const refreshCount = useCallback(() => {
    getUnreadCount()
      .then((res) => setUnreadCount(res.count))
      .catch(() => {
        // Fail silently — badge is non-critical
      });
  }, []);

  useEffect(() => {
    refreshCount();
    const timer = setInterval(refreshCount, 60_000);
    return () => clearInterval(timer);
  }, [refreshCount]);

  // ---- Click-outside to close ----

  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (
        wrapperRef.current &&
        !wrapperRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [open]);

  // ---- Close on Escape ----

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    if (open) document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open]);

  // ---- Fetch notifications on open ----

  const fetchNotifications = useCallback(async () => {
    setPanelState('loading');
    try {
      const list = await getNotifications(false, 20);
      setNotifications(list);
      setPanelState('done');
    } catch {
      setPanelState('error');
    }
  }, []);

  function handleToggle() {
    const next = !open;
    setOpen(next);
    if (next) {
      fetchNotifications();
    }
  }

  // ---- Mark all read ----

  async function handleMarkAllRead() {
    try {
      await markAllRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
      setUnreadCount(0);
    } catch {
      // Best-effort — ignore
    }
  }

  // ---- Mark single read + optional navigation ----

  async function handleItemClick(notification: NotificationOut) {
    // Optimistic update
    if (!notification.read) {
      setNotifications((prev) =>
        prev.map((n) =>
          n.id === notification.id ? { ...n, read: true } : n,
        ),
      );
      setUnreadCount((c) => Math.max(0, c - 1));
      // Fire-and-forget — don't block UI
      markRead(notification.id).catch(() => {
        // Revert on failure
        setNotifications((prev) =>
          prev.map((n) =>
            n.id === notification.id ? { ...n, read: false } : n,
          ),
        );
        setUnreadCount((c) => c + 1);
      });
    }

    if (notification.link) {
      setOpen(false);
      router.push(notification.link);
    }
  }

  // ---- Badge label ----

  const badgeLabel = unreadCount > 9 ? '9+' : String(unreadCount);
  const showBadge = unreadCount > 0;

  return (
    <div className={styles.wrapper} ref={wrapperRef}>
      <button
        type="button"
        className={styles.bellBtn}
        aria-label="Bildirimler"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={handleToggle}
      >
        {/* Bell SVG icon */}
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
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>

        {showBadge && (
          <span className={styles.badge} aria-hidden="true">
            {badgeLabel}
          </span>
        )}
      </button>

      {open && (
        <div
          className={styles.panel}
          role="dialog"
          aria-label="Bildirimler paneli"
        >
          {/* Panel header */}
          <div className={styles.panelHeader}>
            <span className={styles.panelTitle}>Bildirimler</span>
            <button
              type="button"
              className={styles.markAllBtn}
              onClick={handleMarkAllRead}
              disabled={unreadCount === 0}
            >
              Tümünü okundu işaretle
            </button>
          </div>

          {/* Panel body */}
          <div className={styles.list}>
            {panelState === 'loading' && (
              <div className={styles.stateContainer}>
                <LoadingState message="Bildirimler yükleniyor..." />
              </div>
            )}

            {panelState === 'error' && (
              <div className={styles.stateContainer}>
                <ErrorState
                  message="Bildirimler yüklenemedi."
                  onRetry={fetchNotifications}
                />
              </div>
            )}

            {panelState === 'done' && notifications.length === 0 && (
              <div className={styles.stateContainer}>
                <EmptyState title="Henüz bildirim yok." />
              </div>
            )}

            {panelState === 'done' &&
              notifications.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  className={`${styles.item} ${!n.read ? styles.itemUnread : ''}`}
                  onClick={() => handleItemClick(n)}
                >
                  {/* Severity stripe */}
                  <span
                    className={`${styles.severityStripe} ${severityClass(n.severity)}`}
                    aria-hidden="true"
                  />

                  {/* Notification content */}
                  <span className={styles.itemContent}>
                    <span className={styles.itemTitle}>{n.title}</span>
                    {n.body && (
                      <span className={styles.itemBody}>{n.body}</span>
                    )}
                    <span className={styles.itemTime}>
                      {formatRelativeTr(n.created_at)}
                    </span>
                  </span>

                  {/* Unread dot */}
                  {!n.read && (
                    <span className={styles.unreadDot} aria-hidden="true" />
                  )}
                </button>
              ))}
          </div>

          {/* Footer — link to full notifications page */}
          <div className={styles.panelFooter}>
            <Link
              href="/notifications"
              className={styles.viewAllLink}
              onClick={() => setOpen(false)}
            >
              Tümünü gör
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
