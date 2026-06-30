'use client';

import styles from './KpiCard.module.css';

interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
  /** Fractional delta, e.g. 0.12 = +12%. Null/undefined = hidden. */
  delta?: number | null;
  /** When true the "good direction" is negative (lower is better: spend, cpc, cpa). */
  invertDelta?: boolean;
  /**
   * Optional data-quality trust signal.
   * - `ok` (or undefined): silent — renders nothing, does not affect layout.
   * - `warn`: small amber dot in the card corner; tooltip "Veri kalitesi uyarısı — Hesap Taraması'na bakın".
   * - `stale`: small grey clock glyph; tooltip "Veri güncel olmayabilir".
   */
  dataQuality?: 'ok' | 'warn' | 'stale';
}

function fmtDelta(d: number): string {
  const pct = (d * 100).toLocaleString('tr-TR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  return (d >= 0 ? '+' : '') + '%' + pct;
}

export default function KpiCard({ label, value, sub, delta, invertDelta, dataQuality }: KpiCardProps) {
  // delta == null or 0 → no badge shown (0 is ambiguous / not meaningful to show)
  const showDelta = delta !== null && delta !== undefined && delta !== 0;

  let deltaClass = styles.deltaNeutral;
  let arrow = '';
  if (showDelta && delta !== undefined && delta !== null) {
    const isPositive = delta > 0;
    const isGood = invertDelta ? !isPositive : isPositive;
    deltaClass = isGood ? styles.deltaGood : styles.deltaBad;
    arrow = isPositive ? '▲' : '▼'; // ▲ ▼
  }

  return (
    <div className={styles.card}>
      {/* Data-quality trust signal — rendered in card corner, silent when ok/undefined */}
      {dataQuality === 'warn' && (
        <span
          className={styles.dqWarn}
          title="Veri kalitesi uyarısı — Hesap Taraması'na bakın"
          aria-label="Veri kalitesi uyarısı"
          role="img"
        />
      )}
      {dataQuality === 'stale' && (
        <span
          className={styles.dqStale}
          title="Veri güncel olmayabilir"
          aria-label="Veri güncel olmayabilir"
          role="img"
        >
          {/* Clock glyph — Unicode, no external dep */}
          &#x231B;
        </span>
      )}
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
      {showDelta && delta !== undefined && delta !== null && (
        <span className={`${styles.delta} ${deltaClass}`}>
          {arrow} {fmtDelta(delta)}
        </span>
      )}
      {sub && <span className={styles.sub}>{sub}</span>}
    </div>
  );
}
