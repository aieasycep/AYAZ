'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getNotifications,
  markRead,
  markAllRead,
  type NotificationOut,
  type NotificationSeverity,
} from '@/lib/notifications-api';
import AppNav from '@/components/AppNav';
import ErrorBoundary from '@/components/ErrorBoundary';
import { LoadingState, ErrorState, EmptyState } from '@/components/StateViews';
import { parseApiError } from '@/lib/parseApiError';
import styles from './notifications.module.css';

// ---------------------------------------------------------------------------
// Helpers
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

function severityStripeClass(severity: NotificationSeverity): string {
  switch (severity) {
    case 'critical':
      return styles.stripeCritical;
    case 'warning':
      return styles.stripeWarning;
    case 'limit':
      return styles.stripePlan;
    default:
      return styles.stripeInfo;
  }
}

function severityLabel(severity: NotificationSeverity): string {
  switch (severity) {
    case 'critical':
      return 'Kritik';
    case 'warning':
      return 'Uyarı';
    case 'limit':
      return 'Limit';
    default:
      return 'Bilgi';
  }
}

// ---------------------------------------------------------------------------
// Filter types
// ---------------------------------------------------------------------------

type ReadFilter = 'all' | 'unread';
type SeverityFilter = 'all' | NotificationSeverity;

const SEVERITY_OPTS: { value: SeverityFilter; label: string }[] = [
  { value: 'all', label: 'Tümü' },
  { value: 'info', label: 'Bilgi' },
  { value: 'warning', label: 'Uyarı' },
  { value: 'critical', label: 'Kritik' },
  { value: 'limit', label: 'Limit' },
];

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function NotificationsPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  // --- Data state ---
  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  // --- Filter state ---
  const [readFilter, setReadFilter] = useState<ReadFilter>('all');
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');

  // --- Expanded body state ---
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // --- Fetch ---

  const fetchNotifications = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getNotifications(false, 100);
      setNotifications(data);
    } catch (err: unknown) {
      setError(
        parseApiError(err),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchNotifications();
  }, [fetchNotifications]);

  // --- Derived list ---

  const filtered = notifications.filter((n) => {
    if (readFilter === 'unread' && n.read) return false;
    if (severityFilter !== 'all' && n.severity !== severityFilter) return false;
    return true;
  });

  const unreadCount = notifications.filter((n) => !n.read).length;

  // --- Mark all read ---

  async function handleMarkAllRead() {
    if (unreadCount === 0) return;
    setMarkingAll(true);
    try {
      await markAllRead();
      setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    } catch {
      // best-effort; no alert needed — badge will mismatch until next refresh
    } finally {
      setMarkingAll(false);
    }
  }

  // --- Mark single read + optional navigate ---

  async function handleItemClick(n: NotificationOut) {
    // Optimistic update
    if (!n.read) {
      setNotifications((prev) =>
        prev.map((item) =>
          item.id === n.id ? { ...item, read: true } : item,
        ),
      );
      // Fire-and-forget with revert on failure
      markRead(n.id).catch(() => {
        setNotifications((prev) =>
          prev.map((item) =>
            item.id === n.id ? { ...item, read: false } : item,
          ),
        );
      });
    }

    if (n.link) {
      router.push(n.link);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Bildirimler</h1>
            <p className={styles.pageSubtitle}>
              {unreadCount > 0
                ? `${unreadCount} okunmamış bildirim`
                : 'Tüm bildirimler okundu'}
            </p>
          </div>

          <button
            className={styles.markAllBtn}
            onClick={handleMarkAllRead}
            disabled={unreadCount === 0 || markingAll}
            aria-label="Tüm bildirimleri okundu işaretle"
          >
            {markingAll ? 'İşleniyor...' : 'Tümünü okundu işaretle'}
          </button>
        </div>

        {/* Filter bar */}
        <div className={styles.filterBar} role="group" aria-label="Filtreler">
          <button
            className={`${styles.segmentBtn} ${readFilter === 'all' ? styles.segmentBtnActive : ''}`}
            onClick={() => setReadFilter('all')}
            aria-pressed={readFilter === 'all'}
          >
            Tümü <span className={styles.filterCount}>{notifications.length}</span>
          </button>
          <button
            className={`${styles.segmentBtn} ${readFilter === 'unread' ? styles.segmentBtnActive : ''}`}
            onClick={() => setReadFilter('unread')}
            aria-pressed={readFilter === 'unread'}
          >
            Okunmamış
            {unreadCount > 0 && <span className={`${styles.filterCount} ${styles.filterCountUnread}`}>{unreadCount}</span>}
          </button>
          <span className={styles.filterSep} aria-hidden="true" />
          {SEVERITY_OPTS.map((opt) => (
            <button
              key={opt.value}
              className={`${styles.segmentBtn} ${severityFilter === opt.value ? styles.segmentBtnActive : ''}`}
              onClick={() => setSeverityFilter(opt.value)}
              aria-pressed={severityFilter === opt.value}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* List section */}
        <section className={styles.section}>
          {loading ? (
            <LoadingState message="Bildirimler yükleniyor..." />
          ) : error ? (
            <ErrorState message={error} onRetry={fetchNotifications} />
          ) : notifications.length === 0 ? (
            <EmptyState
              title="Henüz bildirim yok"
              description="Yeni bildirimler burada görünecek."
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              title="Sonuç bulunamadı"
              description="Bu filtrelerle eşleşen bildirim yok."
            />
          ) : (
            <ErrorBoundary label="Bildirim listesi">
              <ul className={styles.list} role="list" aria-label="Bildirimler">
                {filtered.map((n) => (
                  <li key={n.id} className={styles.listItem}>
                    <button
                      type="button"
                      className={`${styles.item} ${!n.read ? styles.itemUnread : ''}`}
                      onClick={() => handleItemClick(n)}
                      aria-label={`${severityLabel(n.severity)}: ${n.title}${!n.read ? ' (okunmamış)' : ''}`}
                    >
                      {/* Severity stripe */}
                      <span
                        className={`${styles.severityStripe} ${severityStripeClass(n.severity)}`}
                        aria-hidden="true"
                      />

                      {/* Content */}
                      <span className={styles.content}>
                        <span className={styles.titleRow}>
                          <span className={styles.title}>{n.title}</span>
                          <span
                            className={`${styles.severityBadge} ${styles[`badge_${n.severity}`]}`}
                          >
                            {severityLabel(n.severity)}
                          </span>
                        </span>
                        {n.body && (
                          <span className={`${styles.body} ${expandedIds.has(n.id) ? '' : styles.bodyTruncated}`}>
                            {n.body}
                          </span>
                        )}
                        {n.body && n.body.length > 120 && !expandedIds.has(n.id) && (
                          <button
                            type="button"
                            className={styles.expandBtn}
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedIds((prev) => { const s = new Set(prev); s.add(n.id); return s; });
                            }}
                          >
                            Devamını oku
                          </button>
                        )}
                        <span className={styles.time}>
                          {formatRelativeTr(n.created_at)}
                        </span>
                        {(n.severity === 'critical' || n.severity === 'warning') && n.link && (
                          <span className={styles.goRow}>
                            <a
                              href={n.link}
                              className={styles.goBtn}
                              onClick={(e) => e.stopPropagation()}
                            >
                              Git &rarr;
                            </a>
                          </span>
                        )}
                      </span>

                      {/* Unread dot */}
                      {!n.read && (
                        <span className={styles.unreadDot} aria-hidden="true" />
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            </ErrorBoundary>
          )}
        </section>
      </main>
    </div>
  );
}
