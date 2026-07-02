'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  getTopMovers,
  type TopMover,
  type TopMoversDimension,
  type TopMoversMetric,
} from '@/lib/api';
import { LoadingState, ErrorState, EmptyState } from '@/components/StateViews';
import { parseApiError } from '@/lib/parseApiError';
import { deltaIsGood } from '@/lib/channels';
import styles from './TopMovers.module.css';

// ---------------------------------------------------------------------------
// Types / constants
// ---------------------------------------------------------------------------

interface MetricOption {
  value: TopMoversMetric;
  label: string;
}

const METRIC_OPTIONS: MetricOption[] = [
  { value: 'spend', label: 'Harcama' },
  { value: 'conversions', label: 'Dönüşüm' },
  { value: 'conversion_value', label: 'Dönüşüm Değeri' },
  { value: 'roas', label: 'ROAS' },
  { value: 'clicks', label: 'Tıklama' },
  { value: 'impressions', label: 'Gösterim' },
];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function fmtCurrency(n: number): string {
  return new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: 'TRY',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtInteger(n: number): string {
  return new Intl.NumberFormat('tr-TR').format(Math.round(n));
}

function fmtRoas(n: number): string {
  return (
    n.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

function formatValue(metric: TopMoversMetric, value: number): string {
  switch (metric) {
    case 'spend':
    case 'conversion_value':
      return fmtCurrency(value);
    case 'roas':
      return fmtRoas(value);
    case 'clicks':
    case 'impressions':
    case 'conversions':
      return fmtInteger(value);
    default:
      return String(value);
  }
}

/**
 * Format delta_pct as "+%50" / "-%40" (Turkish convention: % before number).
 * Returns null when delta_pct is null.
 */
function formatDeltaPct(delta_pct: number | null): string | null {
  if (delta_pct === null) return null;
  const abs = Math.abs(delta_pct * 100);
  const pctStr = abs.toLocaleString('tr-TR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
  return (delta_pct >= 0 ? '+' : '-') + '%' + pctStr;
}

// ---------------------------------------------------------------------------
// Sub-component: single mover row
// ---------------------------------------------------------------------------

interface MoverRowProps {
  mover: TopMover;
  metric: TopMoversMetric;
}

function MoverRowItem({ mover, metric }: MoverRowProps) {
  const formattedCurrent = formatValue(metric, mover.current);
  const formattedPrevious = formatValue(metric, mover.previous);
  const pctStr = formatDeltaPct(mover.delta_pct);

  // Renk, metriğin anlamına göre: harcama artışı kötü (kırmızı), diğerlerinde iyi.
  const good = deltaIsGood(metric, mover.delta_pct);
  const badgeClass =
    good === null
      ? styles.deltaBadgeNeutral
      : good
        ? styles.deltaBadgeUp
        : styles.deltaBadgeDown;

  const arrowChar =
    mover.delta_pct === null ? '' : mover.direction === 'up' ? '▲' : '▼';

  const badgeText =
    pctStr === null ? 'yeni' : pctStr;

  return (
    <li className={styles.moverRow}>
      <div className={styles.labelGroup}>
        <span className={styles.label}>{mover.label}</span>
        <span className={styles.prevCurrent}>
          {formattedPrevious} &rarr; {formattedCurrent}
        </span>
      </div>

      <span className={styles.currentValue}>{formattedCurrent}</span>

      <span
        className={`${styles.deltaBadge} ${badgeClass}`}
        aria-label={`Değişim: ${badgeText}`}
      >
        {arrowChar && (
          <span className={styles.arrow} aria-hidden="true">
            {arrowChar}
          </span>
        )}
        {badgeText}
      </span>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export interface TopMoversProps {
  dateFrom: string;
  dateTo: string;
}

export default function TopMovers({ dateFrom, dateTo }: TopMoversProps) {
  const [dimension, setDimension] = useState<TopMoversDimension>('channel');
  const [metric, setMetric] = useState<TopMoversMetric>('spend');

  const [movers, setMovers] = useState<TopMover[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(
    async (
      from: string,
      to: string,
      dim: TopMoversDimension,
      met: TopMoversMetric,
    ) => {
      setLoading(true);
      setError(null);
      try {
        const data = await getTopMovers(from, to, dim, met);
        setMovers(data.movers);
      } catch (err: unknown) {
        setError(parseApiError(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    fetchData(dateFrom, dateTo, dimension, metric);
  }, [dateFrom, dateTo, dimension, metric, fetchData]);

  const controls = (
    <div className={styles.controls}>
      {/* Dimension toggle */}
      <div className={styles.toggle} role="group" aria-label="Boyut seçimi">
        <button
          type="button"
          className={`${styles.toggleBtn} ${dimension === 'channel' ? styles.toggleBtnActive : ''}`}
          aria-pressed={dimension === 'channel'}
          onClick={() => setDimension('channel')}
        >
          Kanal
        </button>
        <button
          type="button"
          className={`${styles.toggleBtn} ${dimension === 'campaign' ? styles.toggleBtnActive : ''}`}
          aria-pressed={dimension === 'campaign'}
          onClick={() => setDimension('campaign')}
        >
          Kampanya
        </button>
      </div>

      {/* Metric select */}
      <select
        className={styles.metricSelect}
        value={metric}
        aria-label="Metrik seçimi"
        onChange={(e) => setMetric(e.target.value as TopMoversMetric)}
      >
        {METRIC_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );

  let body: React.ReactNode;

  if (loading) {
    body = (
      <div className={styles.stateWrapper}>
        <LoadingState message="En çok değişenler yükleniyor..." />
      </div>
    );
  } else if (error) {
    body = (
      <div className={styles.stateWrapper}>
        <ErrorState
          message={error}
          onRetry={() => fetchData(dateFrom, dateTo, dimension, metric)}
        />
      </div>
    );
  } else if (movers.length === 0) {
    body = (
      <div className={styles.stateWrapper}>
        <EmptyState title="Bu dönemde değişim verisi yok." />
      </div>
    );
  } else {
    body = (
      <ul className={styles.list} aria-label="En çok değişenlerin listesi">
        {movers.map((mover) => (
          <MoverRowItem key={mover.key} mover={mover} metric={metric} />
        ))}
      </ul>
    );
  }

  return (
    <>
      {controls}
      {body}
    </>
  );
}
