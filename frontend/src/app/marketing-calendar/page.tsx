'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import AppNav from '@/components/AppNav';
import {
  getOpportunities,
  CATEGORY_LABELS,
  WEIGHT_LABELS,
  type Opportunity,
  type OpportunityCalendar,
  type OppCategory,
  type CommerceWeight,
} from '@/lib/marketing-calendar-api';
import styles from './marketing-calendar.module.css';

// --- Helpers ---

function categoryClass(cat: OppCategory): string {
  switch (cat) {
    case 'ticari':
      return styles.categoryTicari;
    case 'resmi':
      return styles.categoryResmi;
    case 'sezonsal':
      return styles.categorySezonsal;
    case 'dini':
      return styles.categoryDini;
    default:
      return styles.categoryTicari;
  }
}

function weightClass(w: CommerceWeight): string {
  switch (w) {
    case 'yuksek':
      return styles.weightYuksek;
    case 'orta':
      return styles.weightOrta;
    case 'dusuk':
      return styles.weightDusuk;
    default:
      return styles.weightDusuk;
  }
}

// Format date as TR: returns { day, month } strings
function formatTRDateParts(iso: string): { day: string; month: string; monthYear: string } {
  try {
    // Parse the date as local date to avoid UTC offset shifting day
    const [year, m, d] = iso.split('-').map(Number);
    const date = new Date(year, m - 1, d);
    const day = date.toLocaleDateString('tr-TR', { day: 'numeric' });
    const month = date.toLocaleDateString('tr-TR', { month: 'long' });
    const monthYear = date.toLocaleDateString('tr-TR', { month: 'long', year: 'numeric' });
    return { day, month, monthYear };
  } catch {
    return { day: iso, month: '', monthYear: iso };
  }
}

// Group opportunities by "MMMM YYYY" (tr-TR)
function groupByMonth(opportunities: Opportunity[]): Map<string, Opportunity[]> {
  const map = new Map<string, Opportunity[]>();
  for (const opp of opportunities) {
    const { monthYear } = formatTRDateParts(opp.date);
    // Capitalise first letter
    const key = monthYear.charAt(0).toUpperCase() + monthYear.slice(1);
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(opp);
  }
  return map;
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

// --- Opportunity card ---

function OpportunityCard({ opp }: { opp: Opportunity }) {
  const { day, month } = formatTRDateParts(opp.date);
  const isUrgent = opp.status === 'urgent';
  const contentOk = opp.readiness.content_scheduled > 0;
  const budgetOk = opp.readiness.budget_planned;

  return (
    <article className={`${styles.oppCard} ${isUrgent ? styles.oppCardUrgent : ''}`}>
      {/* Header: date block + meta + right meta */}
      <div className={styles.oppCardHeader}>
        <div className={styles.oppDateBlock}>
          <span className={styles.oppDateDay}>{day}</span>
          <span className={styles.oppDateMonth}>{month}</span>
        </div>

        <div className={styles.oppMeta}>
          <div className={styles.oppName}>
            {opp.name}
            {opp.is_approximate && (
              <span className={styles.approxNote}> (yaklaşık)</span>
            )}
          </div>
          <div className={styles.oppChips}>
            <span className={`${styles.categoryBadge} ${categoryClass(opp.category)}`}>
              {CATEGORY_LABELS[opp.category]}
            </span>
            <span className={`${styles.weightChip} ${weightClass(opp.commerce_weight)}`}>
              {WEIGHT_LABELS[opp.commerce_weight]}
            </span>
          </div>
        </div>

        <div className={styles.oppRightMeta}>
          <span className={styles.countdown}>{opp.days_until} gün sonra</span>
          {isUrgent && (
            <span className={styles.urgentBadge}>Acil — şimdi planla</span>
          )}
        </div>
      </div>

      {/* Marketing tip */}
      {opp.marketing_tip && (
        <p className={styles.marketingTip}>{opp.marketing_tip}</p>
      )}

      {/* Readiness indicators */}
      <div className={styles.readinessRow}>
        <span className={styles.readinessLabel}>Hazırlık:</span>
        <span className={`${styles.readinessItem} ${contentOk ? styles.readinessItemOk : ''}`}>
          <span className={styles.readinessIcon}>{contentOk ? '✓' : '✗'}</span>
          {contentOk
            ? `İçerik: ${opp.readiness.content_scheduled} planlandı`
            : 'İçerik: planlanmadı'}
        </span>
        <span className={`${styles.readinessItem} ${budgetOk ? styles.readinessItemOk : ''}`}>
          <span className={styles.readinessIcon}>{budgetOk ? '✓' : '✗'}</span>
          {budgetOk ? 'Bütçe: planlandı' : 'Bütçe: planlanmadı'}
        </span>
      </div>

      {/* Suggested actions */}
      {opp.suggested_actions.length > 0 && (
        <div className={styles.actionsRow}>
          {opp.suggested_actions.map((action) => (
            <Link key={action.href} href={action.href} className={styles.actionLink}>
              {action.label}
            </Link>
          ))}
        </div>
      )}
    </article>
  );
}

// --- Horizon options ---

const HORIZON_OPTIONS: { months: number; label: string }[] = [
  { months: 3, label: '3 ay' },
  { months: 6, label: '6 ay' },
  { months: 12, label: '12 ay' },
];

// --- Main page ---

export default function MarketingCalendarPage() {
  const [data, setData] = useState<OpportunityCalendar | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [horizonMonths, setHorizonMonths] = useState<number>(6);

  const fetchData = useCallback(async (horizon: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getOpportunities(horizon);
      setData(result);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : 'Takvim yüklenemedi',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(horizonMonths);
  }, [fetchData, horizonMonths]);

  function handleHorizonChange(months: number) {
    setHorizonMonths(months);
  }

  const grouped = data ? groupByMonth(data.opportunities) : new Map<string, Opportunity[]>();
  const summary = data?.summary;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Pazarlama Fırsat Takvimi</h1>
          <p className={styles.pageSubtitle}>
            Türkiye&apos;nin önemli ticari ve sezonsal günleri — zamanında planlayın.
          </p>
        </div>

        {/* Summary hero */}
        {!loading && !error && summary && (
          <div className={styles.summaryHero}>
            <div className={styles.statTile}>
              <span className={styles.statTileLabel}>Toplam fırsat</span>
              <span className={styles.statTileValue}>{summary.total}</span>
            </div>
            <div className={styles.statTile}>
              <span className={styles.statTileLabel}>Acil</span>
              <span className={`${styles.statTileValue} ${styles.statTileValueUrgent}`}>
                {summary.urgent}
              </span>
            </div>
            <div className={styles.statTile}>
              <span className={styles.statTileLabel}>Bu ay</span>
              <span className={styles.statTileValue}>{summary.this_month}</span>
            </div>
            <div className={styles.statTile}>
              <span className={styles.statTileLabel}>Yüksek hacim</span>
              <span className={`${styles.statTileValue} ${styles.statTileValueHigh}`}>
                {summary.high_weight}
              </span>
            </div>
          </div>
        )}

        {/* Horizon selector */}
        <div className={styles.horizonBar}>
          <span className={styles.horizonLabel}>Ufuk:</span>
          {HORIZON_OPTIONS.map((opt) => (
            <button
              key={opt.months}
              type="button"
              className={`${styles.horizonBtn} ${horizonMonths === opt.months ? styles.horizonBtnActive : ''}`}
              onClick={() => handleHorizonChange(opt.months)}
              disabled={loading}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Content area */}
        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <div className={styles.stateBox}>
            <span className={styles.errorText}>{error}</span>
            <br />
            <button className={styles.retryBtn} onClick={() => fetchData(horizonMonths)}>
              Tekrar Dene
            </button>
          </div>
        ) : grouped.size === 0 ? (
          <div className={styles.stateBox}>
            <span className={styles.muted}>Bu dönemde yaklaşan fırsat yok.</span>
          </div>
        ) : (
          <div className={styles.timeline}>
            {Array.from(grouped.entries()).map(([monthLabel, opportunities]) => (
              <section key={monthLabel} className={styles.monthGroup}>
                <h2 className={styles.monthHeader}>{monthLabel}</h2>
                {opportunities.map((opp) => (
                  <OpportunityCard key={`${opp.date}-${opp.name}`} opp={opp} />
                ))}
              </section>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
