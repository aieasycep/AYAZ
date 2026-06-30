'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import AppNav from '@/components/AppNav';
import {
  getRecommendationFeed,
  getWeeklyStrategy,
  applyRecommendationAction,
  CATEGORY_LABELS,
  STATUS_LABELS,
  type Recommendation,
  type RecommendationFeed,
  type WeeklyStrategy,
  type RecommendationStatus,
  type RecommendationCategory,
} from '@/lib/recommendations-api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './recommendations.module.css';

// --- Helpers ---

// The audit "Sağlık Puanı" (health score) is the SAME account-wide number
// attached to every audit-derived recommendation card — showing it on each
// card is redundant and not distinguishing. We surface it once, in the page
// summary band, and hide the per-card metric only for this specific label.
const HEALTH_SCORE_METRIC_LABEL = 'Sağlık Puanı';

function categoryClass(category: RecommendationCategory): string {
  switch (category) {
    case 'budget':
      return styles.categoryBudget;
    case 'performance':
      return styles.categoryPerformance;
    case 'tracking':
      return styles.categoryTracking;
    case 'content':
      return styles.categoryContent;
    case 'inbox':
      return styles.categoryInbox;
    case 'goal':
      return styles.categoryGoal;
    case 'audit':
      return styles.categoryAudit;
    case 'benchmark':
      return styles.categoryBenchmark;
    default:
      return styles.categoryPerformance;
  }
}

function impactClass(impact: Recommendation['impact']): string {
  switch (impact) {
    case 'high':
      return styles.impactHigh;
    case 'medium':
      return styles.impactMedium;
    case 'low':
      return styles.impactLow;
    default:
      return styles.impactLow;
  }
}

function statusPillClass(status: RecommendationStatus): string {
  switch (status) {
    case 'accepted':
      return styles.statusAccepted;
    case 'snoozed':
      return styles.statusSnoozed;
    case 'dismissed':
      return styles.statusDismissed;
    default:
      return styles.statusDismissed;
  }
}

function formatTRDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('tr-TR', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
}

// --- Weekly Strategy hero ---

function WeeklyStrategyHero({ strategy }: { strategy: WeeklyStrategy }) {
  return (
    <div className={styles.strategyHero}>
      <div className={styles.strategyMeta}>
        <span className={styles.weekBadge}>{strategy.week_label}</span>
        <span
          className={`${styles.sourceChip} ${
            strategy.source === 'ai'
              ? styles.sourceChipAi
              : styles.sourceChipTemplate
          }`}
        >
          {strategy.source === 'ai' ? 'Yapay zeka' : 'Otomatik özet'}
        </span>
      </div>
      <p className={styles.strategyHeadline}>{strategy.headline}</p>
      <p className={styles.strategyNarrative}>{strategy.narrative}</p>
      {strategy.focus_areas.length > 0 && (
        <div className={styles.focusGrid}>
          {strategy.focus_areas.map((area, i) => (
            <div key={i} className={styles.focusCard}>
              <div className={styles.focusCardTitle}>{area.title}</div>
              <div className={styles.focusCardDetail}>{area.detail}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Recommendation card ---

interface RecCardProps {
  rec: Recommendation;
  onStatusChange: (key: string, newStatus: RecommendationStatus, snoozedUntil: string | null) => void;
}

function RecCard({ rec, onStatusChange }: RecCardProps) {
  const [pending, setPending] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const isOpen = rec.status === 'open';
  const isDimmed = rec.status === 'dismissed';

  async function handleAction(
    action: 'accept' | 'snooze' | 'dismiss' | 'reopen',
    snooze_days?: number,
  ) {
    setPending(action);
    setActionError(null);
    try {
      const result = await applyRecommendationAction(rec.key, {
        action,
        ...(snooze_days !== undefined ? { snooze_days } : {}),
      });
      onStatusChange(rec.key, result.status, result.snoozed_until);
    } catch (err: unknown) {
      setActionError(
        parseApiError(err),
      );
    } finally {
      setPending(null);
    }
  }

  return (
    <div
      className={`${styles.recCard} ${isDimmed ? styles.recCardDimmed : ''}`}
      data-impact={rec.impact}
    >
      {/* Header row: chips */}
      <div className={styles.recCardHeader}>
        <div className={styles.recCardChips}>
          <span
            className={`${styles.categoryBadge} ${categoryClass(rec.category)}`}
          >
            {rec.category_label || CATEGORY_LABELS[rec.category] || rec.category}
          </span>
          <span className={`${styles.impactChip} ${impactClass(rec.impact)}`}>
            {rec.impact_label}
          </span>
          <span className={styles.effortChip}>{rec.effort_label}</span>
          {!isOpen && (
            <span
              className={`${styles.statusPill} ${statusPillClass(rec.status)}`}
            >
              {STATUS_LABELS[rec.status]}
            </span>
          )}
        </div>
      </div>

      {/* Title */}
      <div className={styles.recCardTitle}>{rec.title}</div>

      {/* Rationale */}
      <p className={styles.recCardRationale}>{rec.rationale}</p>

      {/* Supporting metric — the account-wide health score is shown once in
          the page summary band instead of repeating on every card. */}
      {rec.metric && rec.metric.label !== HEALTH_SCORE_METRIC_LABEL && (
        <div className={styles.recCardMetric}>
          <span className={styles.recCardMetricLabel}>{rec.metric.label}:</span>
          <span className={styles.recCardMetricValue}>{rec.metric.value}</span>
        </div>
      )}

      {/* Snoozed until */}
      {rec.status === 'snoozed' && rec.snoozed_until && (
        <p className={styles.snoozedUntil}>
          Ertelendi: {formatTRDate(rec.snoozed_until)}
        </p>
      )}

      {/* Actions */}
      <div className={styles.recCardActions}>
        <Link href={rec.action_href} className={styles.actionLinkBtn}>
          {rec.action_label}{/* arrow is added by CSS ::after */}
        </Link>

        {isOpen ? (
          <>
            <button
              className={`${styles.actionBtn} ${pending === 'accept' ? styles.actionBtnPending : ''}`}
              onClick={() => handleAction('accept')}
              disabled={pending !== null}
            >
              {pending === 'accept' ? '...' : 'Kabul Et'}
            </button>
            <button
              className={`${styles.actionBtn} ${pending === 'snooze' ? styles.actionBtnPending : ''}`}
              onClick={() => handleAction('snooze', 7)}
              disabled={pending !== null}
            >
              {pending === 'snooze' ? '...' : 'Ertele'}
            </button>
            <button
              className={`${styles.actionBtn} ${pending === 'dismiss' ? styles.actionBtnPending : ''}`}
              onClick={() => handleAction('dismiss')}
              disabled={pending !== null}
            >
              {pending === 'dismiss' ? '...' : 'Reddet'}
            </button>
          </>
        ) : (
          <button
            className={`${styles.actionBtn} ${styles.actionBtnReopen} ${pending === 'reopen' ? styles.actionBtnPending : ''}`}
            onClick={() => handleAction('reopen')}
            disabled={pending !== null}
          >
            {pending === 'reopen' ? '...' : 'Geri Al'}
          </button>
        )}
      </div>

      {/* Inline error */}
      {actionError && (
        <p className={styles.actionError}>{actionError}</p>
      )}
    </div>
  );
}

// --- Filter tabs ---

type FilterTab = RecommendationStatus | 'all';

interface FilterTabItem {
  key: FilterTab;
  label: string;
  count: number;
}

// --- Loading skeleton ---

function LoadingSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonHero}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// --- Main page ---

export default function RecommendationsPage() {
  const [feed, setFeed] = useState<RecommendationFeed | null>(null);
  const [strategy, setStrategy] = useState<WeeklyStrategy | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<FilterTab>('open');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [feedResult, strategyResult] = await Promise.all([
        getRecommendationFeed(),
        getWeeklyStrategy(),
      ]);
      setFeed(feedResult);
      setStrategy(strategyResult);
    } catch (err: unknown) {
      setError(
        parseApiError(err),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  function handleStatusChange(
    key: string,
    newStatus: RecommendationStatus,
    snoozedUntil: string | null,
  ) {
    setFeed((prev) => {
      if (!prev) return prev;

      const oldRec = prev.recommendations.find((r) => r.key === key);
      const oldStatus = oldRec?.status;

      const updated = prev.recommendations.map((r) =>
        r.key === key ? { ...r, status: newStatus, snoozed_until: snoozedUntil } : r,
      );

      // Recompute summary counts
      const summary = { ...prev.summary };
      if (oldStatus && oldStatus !== newStatus) {
        if (oldStatus === 'open') summary.open = Math.max(0, summary.open - 1);
        else if (oldStatus === 'accepted') summary.accepted = Math.max(0, summary.accepted - 1);
        else if (oldStatus === 'snoozed') summary.snoozed = Math.max(0, summary.snoozed - 1);
        else if (oldStatus === 'dismissed') summary.dismissed = Math.max(0, summary.dismissed - 1);

        if (newStatus === 'open') summary.open += 1;
        else if (newStatus === 'accepted') summary.accepted += 1;
        else if (newStatus === 'snoozed') summary.snoozed += 1;
        else if (newStatus === 'dismissed') summary.dismissed += 1;
      }

      return { ...prev, recommendations: updated, summary };
    });
  }

  // The account health score is identical across every audit-derived
  // recommendation — pull it from the first one that has it so it can be
  // shown exactly once, instead of repeating on every matching card.
  const healthScore = feed?.recommendations.find(
    (r) => r.metric?.label === HEALTH_SCORE_METRIC_LABEL,
  )?.metric?.value;

  // Build filter tabs
  const summary = feed?.summary;
  const tabs: FilterTabItem[] = [
    { key: 'open', label: 'Açık', count: summary?.open ?? 0 },
    { key: 'accepted', label: 'Kabul edilen', count: summary?.accepted ?? 0 },
    { key: 'snoozed', label: 'Ertelenen', count: summary?.snoozed ?? 0 },
    { key: 'dismissed', label: 'Reddedilen', count: summary?.dismissed ?? 0 },
    { key: 'all', label: 'Tümü', count: summary?.total ?? 0 },
  ];

  const visibleRecs =
    feed?.recommendations.filter((r) =>
      activeTab === 'all' ? true : r.status === activeTab,
    ) ?? [];

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Öneri Merkezi</h1>
            <p className={styles.pageSubtitle}>
              Tüm ekipler için yapay zeka destekli aksiyon akışı — bütçe, performans,
              ölçümleme, içerik ve daha fazlası tek yerden.
            </p>
          </div>
          {healthScore && (
            <span className={styles.healthScoreBadge} title="Hesap genelinde denetim sağlık puanı">
              {HEALTH_SCORE_METRIC_LABEL}: <strong>{healthScore}</strong>
            </span>
          )}
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <div className={styles.sectionCard}>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchData}>
                Tekrar Dene
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Weekly strategy hero */}
            {strategy && <WeeklyStrategyHero strategy={strategy} />}

            {/* Filter tabs */}
            <div>
              <div className={styles.filterBar}>
                {tabs.map((tab) => (
                  <button
                    key={tab.key}
                    className={`${styles.filterTab} ${activeTab === tab.key ? styles.filterTabActive : ''}`}
                    onClick={() => setActiveTab(tab.key)}
                  >
                    {tab.label}
                    <span className={styles.filterTabBadge}>{tab.count}</span>
                  </button>
                ))}
              </div>

              {/* Feed */}
              <div className={styles.feed} style={{ marginTop: '1rem' }}>
                {visibleRecs.length === 0 ? (
                  <div className={styles.emptyState}>
                    Bu kategoride öneri yok.
                  </div>
                ) : (
                  visibleRecs.map((rec) => (
                    <RecCard
                      key={rec.key}
                      rec={rec}
                      onStatusChange={handleStatusChange}
                    />
                  ))
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
