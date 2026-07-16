'use client';

import { useState, useCallback, useEffect } from 'react';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import EmptyState from '@/components/EmptyState';
import DateRangePresets, {
  detectPreset,
  computePreset,
  type PresetKey,
} from '@/components/DateRangePresets';
import {
  getAttributionSummary,
  type AttributionSummary,
  type AttributionChannelRow,
  type AttributionSourceType,
} from '@/lib/attribution-api';
import { channelLabel } from '@/lib/channels';
import { parseApiError } from '@/lib/parseApiError';
import { formatDateRangeTR } from '@/lib/formatDate';
import { downloadRowsAsCsv } from '@/lib/csv';
import styles from './atif.module.css';

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

const tryFmt = new Intl.NumberFormat('tr-TR', {
  style: 'currency',
  currency: 'TRY',
  maximumFractionDigits: 0,
});

function fmtCurrency(n: number): string {
  return tryFmt.format(n);
}

function fmtNumber(n: number): string {
  return Math.round(n).toLocaleString('tr-TR');
}

function fmtRoas(n: number): string {
  return (
    n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + 'x'
  );
}

function fmtFactor(n: number): string {
  return (
    n.toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '×'
  );
}

// ---------------------------------------------------------------------------
// Days helpers — the backend endpoint takes `days` (1-90, rolling window
// ending today), not an arbitrary date_from/date_to range. We still use the
// shared DateRangePresets component for a familiar, consistent picker; the
// selected range is converted to a day-count and clamped to what the API
// accepts. The section header always shows the ACTUAL period the backend
// used (data.date_from/date_to) so there is never a mismatch with what the
// user picked (e.g. "Geçen ay" still resolves to a rolling N-day window).
// ---------------------------------------------------------------------------

const MIN_DAYS = 1;
const MAX_DAYS = 90;
const DEFAULT_PRESET: PresetKey = 'son90';

function daysBetweenInclusive(from: string, to: string): number {
  const a = new Date(`${from}T00:00:00`);
  const b = new Date(`${to}T00:00:00`);
  return Math.round((b.getTime() - a.getTime()) / 86400000) + 1;
}

function clampDays(n: number): number {
  return Math.min(MAX_DAYS, Math.max(MIN_DAYS, n));
}

// ---------------------------------------------------------------------------
// Inflation factor → tone + caption
// ---------------------------------------------------------------------------

type Tone = 'good' | 'warn' | 'critical' | 'neutral';

function inflationTone(factor: number | null): Tone {
  if (factor === null) return 'neutral';
  if (factor > 2) return 'critical';
  if (factor >= 1.2) return 'warn';
  if (factor >= 0.95) return 'good';
  // factor < 0.95 → platformlar GA4 ücretli-kanalın ALTINDA raporluyor; bu bir
  // tutarsızlık, "Tutarlı" (yeşil) DEĞİL. Caption ile uyumlu olması için uyarı.
  return 'warn';
}

function inflationBadgeText(factor: number | null): string {
  if (factor === null) return 'Hesaplanamadı';
  if (factor > 2) return 'Ciddi şişkin';
  if (factor >= 1.2) return 'Şişkin';
  if (factor >= 0.95) return 'Tutarlı';
  // Under-report bandı: rozet metni caption'daki "altında iddia ediyor" ile eşleşir.
  return 'Eksik raporluyor';
}

function inflationCaption(factor: number | null): string {
  if (factor === null) {
    return 'GA4’te ücretli-kanal dönüşümü bulunamadı — şişme faktörü hesaplanamıyor.';
  }
  if (factor > 1.05) {
    return `Platformlar GA4 ücretli-kanal dönüşümüne göre ${fmtFactor(factor)} fazla iddia ediyor.`;
  }
  if (factor < 0.95) {
    return `Platformlar GA4 ücretli-kanalın altında dönüşüm iddia ediyor (${fmtFactor(factor)}).`;
  }
  return 'Platform iddiaları GA4 ücretli-kanal verisiyle tutarlı.';
}

function pillClass(tone: Tone): string {
  switch (tone) {
    case 'good':
      return styles.pillGood;
    case 'warn':
      return styles.pillWarn;
    case 'critical':
      return styles.pillCritical;
    default:
      return styles.pillNeutral;
  }
}

// ---------------------------------------------------------------------------
// KPI tile
// ---------------------------------------------------------------------------

interface KpiTileProps {
  label: string;
  value: string;
  caption?: string;
  highlight?: boolean;
  badge?: { text: string; tone: Tone };
}

function KpiTile({ label, value, caption, highlight, badge }: KpiTileProps) {
  return (
    <div className={`${styles.kpiCard} ${highlight ? styles.kpiCardHighlight : ''}`}>
      <div className={styles.kpiLabelRow}>
        <span className={styles.kpiLabel}>{label}</span>
      </div>
      <span className={highlight ? styles.kpiValueHighlight : styles.kpiValue}>{value}</span>
      {badge && <span className={`${styles.pill} ${pillClass(badge.tone)}`}>{badge.text}</span>}
      {caption && <span className={styles.kpiCaption}>{caption}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channel table
// ---------------------------------------------------------------------------

function SourceTypeBadge({ type }: { type: AttributionSourceType }) {
  return (
    <span className={type === 'ad' ? styles.sourceBadgeAd : styles.sourceBadgeAnalytics}>
      {type === 'ad' ? 'Reklam' : 'Analitik'}
    </span>
  );
}

function AttributionChannelTable({ rows }: { rows: AttributionChannelRow[] }) {
  return (
    <div className={`${styles.tableWrap} table-scroll-hint`}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.th}>Kanal</th>
            <th className={styles.th}>Tür</th>
            <th className={`${styles.th} ${styles.right}`}>Harcama</th>
            <th className={`${styles.th} ${styles.right}`}>Dönüşüm</th>
            <th className={`${styles.th} ${styles.right}`}>Gelir</th>
            <th className={`${styles.th} ${styles.right}`}>ROAS</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            // ₺0 harcamalı analitik kaynaklarda (GA4, Search Console) ROAS
            // matematiksel olarak tanımsızdır — "0.00x" göstermek yanıltıcı
            // olur (bkz. ChannelTable.tsx'teki aynı düzeltme).
            const roasNA = row.source_type === 'analytics' || row.spend === 0;
            return (
              <tr key={row.key} className={styles.row}>
                <td className={`${styles.td} ${styles.channelCell}`}>
                  {channelLabel(row.key)}
                </td>
                <td className={styles.td}>
                  <SourceTypeBadge type={row.source_type} />
                </td>
                <td className={`${styles.td} ${styles.right}`}>{fmtCurrency(row.spend)}</td>
                <td className={`${styles.td} ${styles.right}`}>{fmtNumber(row.conversions)}</td>
                <td className={`${styles.td} ${styles.right}`}>
                  {fmtCurrency(row.conversion_value)}
                </td>
                <td className={`${styles.td} ${styles.right}`}>
                  {roasNA ? (
                    <span
                      className={styles.muted}
                      title="Harcaması olmayan kaynaklarda ROAS anlamsızdır"
                    >
                      —
                    </span>
                  ) : (
                    fmtRoas(row.roas)
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <>
      <div className={styles.skeletonKpiGrid}>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className={`${styles.skeleton} ${styles.skeletonCard}`} />
        ))}
      </div>
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const INITIAL_RANGE = computePreset(DEFAULT_PRESET);
const INITIAL_DAYS = clampDays(daysBetweenInclusive(INITIAL_RANGE.from, INITIAL_RANGE.to));

export default function AtifPage() {
  const [days, setDays] = useState<number>(INITIAL_DAYS);
  const [activePreset, setActivePreset] = useState<PresetKey | null>(DEFAULT_PRESET);
  const [data, setData] = useState<AttributionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getAttributionSummary(d);
      setData(result);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(days);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handlePresetSelect(from: string, to: string) {
    const newDays = clampDays(daysBetweenInclusive(from, to));
    setDays(newDays);
    setActivePreset(detectPreset(from, to));
    fetchData(newDays);
  }

  function handleCsvExport() {
    if (!data) return;
    downloadRowsAsCsv(
      data.channels.map((c) => ({
        kanal: channelLabel(c.key),
        tur: c.source_type === 'ad' ? 'Reklam' : 'Analitik',
        harcama: c.spend,
        donusum: c.conversions,
        gelir: c.conversion_value,
        roas: c.source_type === 'analytics' || c.spend === 0 ? '' : c.roas,
      })),
      `atif-${data.date_from}-${data.date_to}.csv`,
      [
        { key: 'kanal', label: 'Kanal' },
        { key: 'tur', label: 'Tür' },
        { key: 'harcama', label: 'Harcama' },
        { key: 'donusum', label: 'Dönüşüm' },
        { key: 'gelir', label: 'Gelir' },
        { key: 'roas', label: 'ROAS' },
      ],
    );
  }

  const hasChannels = !!data && data.channels.length > 0;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Atıf</h1>
          <p className={styles.pageSubtitle}>
            Reklam platformlarının kendi raporladığı dönüşümler ile GA4&apos;ün ölçtüğü
            gerçek dönüşümü yan yana karşılaştırın — çift sayım yok.
          </p>
        </div>

        {/* Date range */}
        <section className={styles.presetsRow}>
          <DateRangePresets onSelect={handlePresetSelect} activePreset={activePreset} />
          <p className={styles.presetsNote}>
            Seçilen aralık, bugünden geriye doğru gün sayısına çevrilir (en fazla 90 gün).
          </p>
        </section>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <SectionCard>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={() => fetchData(days)}>
                Tekrar Dene
              </button>
            </div>
          </SectionCard>
        ) : data ? (
          hasChannels ? (
            <>
              {/* Data-quality warning banner — ayrı ve dikkat çekici (amber),
                  mavi info callout'tan bağımsız. Yalnız backend not döndürdüğünde. */}
              {data.data_quality?.note && (
                <div className={styles.warningBanner} role="alert">
                  <span className={styles.warningIcon} aria-hidden="true">
                    ⚠
                  </span>
                  <p className={styles.warningText}>{data.data_quality.note}</p>
                </div>
              )}

              {/* KPI strip */}
              <div className={styles.kpiGrid}>
                <KpiTile
                  label="Blended ROAS (Gerçek)"
                  value={fmtRoas(data.blended_roas)}
                  highlight
                  badge={{ text: 'Gerçek', tone: 'good' }}
                  caption={
                    data.ga4_paid_revenue === 0
                      ? 'GA4 ücretli-kanal geliri sıfır — bağlantıyı kontrol edin'
                      : 'GA4 ücretli-kanal geliri ÷ reklam harcaması'
                  }
                />
                <KpiTile
                  label="Medya Verimliliği (MER)"
                  value={fmtRoas(data.mer)}
                  caption="Tüm GA4 geliri ÷ reklam harcaması (organik dahil)"
                />
                <KpiTile
                  label="Reklam Harcaması"
                  value={fmtCurrency(data.ad_spend)}
                  caption="Yalnızca reklam platformları (Google Ads + Meta Ads)"
                />
                <KpiTile
                  label="GA4 Ücretli Dönüşüm"
                  value={fmtNumber(data.ga4_paid_conversions)}
                  caption={`Toplam GA4: ${fmtNumber(data.ga4_conversions)}`}
                />
                <KpiTile
                  label="Şişme Faktörü"
                  value={data.inflation_factor !== null ? fmtFactor(data.inflation_factor) : '—'}
                  badge={{
                    text: inflationBadgeText(data.inflation_factor),
                    tone: inflationTone(data.inflation_factor),
                  }}
                  caption={inflationCaption(data.inflation_factor)}
                />
              </div>

              {/* Explanation callout */}
              <div className={styles.infoCallout}>
                <span className={styles.infoIcon} aria-hidden="true">
                  ⓘ
                </span>
                <p className={styles.infoText}>
                  Reklam platformları kendi dönüşümlerini raporlar ve çakışır; GA4&apos;ün
                  ücretli-kanal grupları (Paid Search/Paid Social/...) bu iddialarla
                  ELMA-ELMA karşılaştırılabilir tek-kaynak-doğrusudur. Blended ROAS = GA4
                  ücretli-kanal geliri ÷ toplam reklam harcaması. MER ise organik dahil
                  tüm GA4 gelirini reklam harcamasıyla oranlar — ayrı bir verimlilik ölçüsü.
                </p>
              </div>

              {/* Channel table */}
              <SectionCard
                title="Kanal Kırılımı"
                right={
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                    <span className={styles.periodLabel}>
                      {formatDateRangeTR(data.date_from, data.date_to)}
                    </span>
                    <button className={styles.csvBtn} onClick={handleCsvExport}>
                      CSV İndir
                    </button>
                  </div>
                }
              >
                <AttributionChannelTable rows={data.channels} />
              </SectionCard>
            </>
          ) : (
            <SectionCard>
              <EmptyState
                title="Atıf için henüz veri yok"
                subtitle="Atıf karşılaştırması için en az bir reklam platformu (Google Ads veya Meta Ads) ve Google Analytics 4 bağlayın."
                action={{ label: 'Bağlantıları Yönet', href: '/integrations' }}
              />
            </SectionCard>
          )
        ) : null}
      </main>
    </div>
  );
}
