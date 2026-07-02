'use client';

import { useState, useEffect, useCallback } from 'react';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import {
  getBenchmark,
  POSITION_LABELS,
  type Benchmark,
  type BenchmarkMetric,
  type BenchmarkChannel,
  type BenchmarkInsight,
  type BenchPosition,
} from '@/lib/benchmark-api';
import { parseApiError } from '@/lib/parseApiError';
import { downloadRowsAsCsv } from '@/lib/csv';
import styles from './benchmark.module.css';

// --- Formatters ---

function fmtValue(value: number, unit: '%' | '₺' | 'x'): string {
  if (unit === '₺') {
    return (
      '₺' +
      value.toLocaleString('tr-TR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    );
  }
  if (unit === '%') {
    return (
      '%' +
      value.toLocaleString('tr-TR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    );
  }
  // 'x'
  return (
    value.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

function fmtShort(value: number, unit: '%' | '₺' | 'x'): string {
  if (unit === '₺') {
    return '₺' + value.toLocaleString('tr-TR', { maximumFractionDigits: 2 });
  }
  if (unit === '%') {
    return '%' + value.toLocaleString('tr-TR', { maximumFractionDigits: 1 });
  }
  return value.toLocaleString('tr-TR', { maximumFractionDigits: 2 }) + 'x';
}

// --- Position helpers ---

function positionBadgeClass(pos: BenchPosition): string {
  switch (pos) {
    case 'strong':
      return styles.positionStrong;
    case 'average':
      return styles.positionAverage;
    case 'weak':
      return styles.positionWeak;
  }
}

function markerClass(pos: BenchPosition): string {
  switch (pos) {
    case 'strong':
      return styles.markerStrong;
    case 'average':
      return styles.markerAverage;
    case 'weak':
      return styles.markerWeak;
  }
}

// --- Zone Legend ---

function ZoneLegend() {
  return (
    <div className={styles.zoneLegend}>
      <span className={styles.zoneDot} data-zone="strong" />
      <span className={styles.zoneLegendLabel}>Güçlü</span>
      <span className={styles.zoneDot} data-zone="average" />
      <span className={styles.zoneLegendLabel}>Ortalama</span>
      <span className={styles.zoneDot} data-zone="weak" />
      <span className={styles.zoneLegendLabel}>Zayıf</span>
    </div>
  );
}

// --- RangeBar component ---
//
// Renders a horizontal bar spanning ref_low → ref_high (relative to a wider
// axis). The axis minimum is 0; the axis maximum is ref_high * 1.5 so there is
// visible space above ref_high when your_value exceeds it.

interface RangeBarProps {
  metric: BenchmarkMetric;
}

function RangeBar({ metric }: RangeBarProps) {
  const { your_value, ref_low, ref_mid, ref_high, unit, position } = metric;

  // Build axis bounds with some padding beyond ref_high
  const axisMax = Math.max(ref_high * 1.5, your_value * 1.1, ref_high + 1);
  const axisMin = 0;
  const axisRange = axisMax - axisMin;

  function toPct(v: number): number {
    return Math.max(0, Math.min(100, ((v - axisMin) / axisRange) * 100));
  }

  const lowPct = toPct(ref_low);
  const highPct = toPct(ref_high);
  const midPct = toPct(ref_mid);

  // Clamp the marker to [0, 100] for visual placement; track if it was clamped.
  const rawMarkerPct = toPct(your_value);
  const markerPct = Math.max(0, Math.min(100, rawMarkerPct));
  const isAbove = your_value > ref_high;
  const isBelow = your_value < ref_low;
  const arrowLabel = isAbove ? '↑' : isBelow ? '↓' : null;

  return (
    <div className={styles.metricCenter}>
      <div className={styles.rangeBarWrap}>
        <div className={styles.rangeBarTrack}>
          {/* Colored reference segment */}
          <div
            className={styles.rangeBarFill}
            style={{
              left: `${lowPct}%`,
              width: `${highPct - lowPct}%`,
            }}
          />
          {/* Midpoint tick */}
          <div
            className={styles.rangeBarMid}
            style={{ left: `${midPct}%` }}
          />
          {/* Your value marker */}
          <div
            className={`${styles.rangeBarMarker} ${markerClass(position)}`}
            style={{ left: `${markerPct}%` }}
          >
            {arrowLabel && (
              <span className={styles.rangeBarArrow}>{arrowLabel}</span>
            )}
          </div>
        </div>
      </div>
      {/* Low / Mid / High labels */}
      <div className={styles.rangeLabels}>
        <span>{fmtShort(ref_low, unit)}</span>
        <span style={{ color: 'var(--color-primary)', opacity: 0.7 }}>
          ort. {fmtShort(ref_mid, unit)}
        </span>
        <span>{fmtShort(ref_high, unit)}</span>
      </div>
    </div>
  );
}

// --- MetricRow ---

function MetricRow({ metric }: { metric: BenchmarkMetric }) {
  const lowerIsBetter = !metric.higher_is_better;

  return (
    <div className={styles.metricRow}>
      {/* Left: label + your value */}
      <div className={styles.metricLeft}>
        <div className={styles.metricLabel}>{metric.label}</div>
        {lowerIsBetter && (
          <div className={styles.metricHint}>(düşük daha iyi)</div>
        )}
        <div className={styles.metricYourValue}>
          {fmtValue(metric.your_value, metric.unit)}
        </div>
      </div>

      {/* Center: range bar */}
      <RangeBar metric={metric} />

      {/* Right: position badge + verdict */}
      <div className={styles.metricRight}>
        <span
          className={`${styles.positionBadge} ${positionBadgeClass(metric.position)}`}
        >
          {POSITION_LABELS[metric.position]}
        </span>
        <div className={styles.metricVerdict}>{metric.verdict}</div>
      </div>
    </div>
  );
}

// --- InsightsSection ---
//
// Prioritized, cross-metric takeaways (biggest opportunity / traffic-vs-conversion
// diagnostic / channel reallocation) so the page tells the user what to DO, not
// just where each metric sits.

const INSIGHT_META: Record<
  BenchmarkInsight['severity'],
  { label: string; icon: string }
> = {
  opportunity: { label: 'Fırsat', icon: '↑' },
  diagnostic: { label: 'Teşhis', icon: '🔎' },
  strength: { label: 'Aksiyon', icon: '➜' },
};

function insightCardClass(sev: BenchmarkInsight['severity']): string {
  switch (sev) {
    case 'opportunity':
      return styles.insightOpportunity;
    case 'diagnostic':
      return styles.insightDiagnostic;
    case 'strength':
      return styles.insightStrength;
  }
}

function InsightsSection({ insights }: { insights: BenchmarkInsight[] }) {
  return (
    <div className={styles.sectionCard}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Öncelikli İçgörüler</span>
      </div>
      <div className={styles.insightList}>
        {insights.map((ins, i) => (
          <div
            key={i}
            className={`${styles.insightCard} ${insightCardClass(ins.severity)}`}
          >
            <span className={styles.insightIcon} aria-hidden="true">
              {INSIGHT_META[ins.severity].icon}
            </span>
            <div className={styles.insightBody}>
              <div className={styles.insightHead}>
                <span className={styles.insightBadge}>
                  {INSIGHT_META[ins.severity].label}
                </span>
                <span className={styles.insightTitle}>{ins.title}</span>
              </div>
              <p className={styles.insightDetail}>{ins.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- ChannelsSection ---

function ChannelsSection({ channels }: { channels: BenchmarkChannel[] }) {
  if (channels.length === 0) {
    return (
      <div className={styles.stateBox}>
        <span className={styles.muted}>Kanal verisi bulunamadı.</span>
      </div>
    );
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className={styles.channelTable}>
        <thead>
          <tr>
            <th>Kanal</th>
            <th className={styles.numCol}>ROAS</th>
            <th>ROAS Konumu</th>
            <th className={styles.numCol}>CTR</th>
            <th>CTR Konumu</th>
          </tr>
        </thead>
        <tbody>
          {channels.map((ch) => (
            <tr key={ch.channel}>
              <td>
                <span className={styles.channelLabel}>{ch.label}</span>
              </td>
              <td className={`${styles.numCol} ${styles.roasValue}`}>
                {ch.roas.toLocaleString('tr-TR', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
                x
              </td>
              <td>
                <span
                  className={`${styles.positionBadge} ${positionBadgeClass(ch.roas_position)}`}
                >
                  {POSITION_LABELS[ch.roas_position]}
                </span>
              </td>
              <td className={styles.numCol}>
                {ch.ctr.toLocaleString('tr-TR', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
                %
              </td>
              <td>
                <span
                  className={`${styles.positionBadge} ${positionBadgeClass(ch.ctr_position)}`}
                >
                  {POSITION_LABELS[ch.ctr_position]}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Loading skeleton ---

function LoadingSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonBanner}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSectionSm}`} />
    </>
  );
}

// --- Main page ---

export default function BenchmarkPage() {
  const [data, setData] = useState<Benchmark | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchBenchmark = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getBenchmark();
      setData(result);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBenchmark();
  }, [fetchBenchmark]);

  const noData =
    data !== null &&
    data.metrics.length === 0 &&
    data.channels.length === 0;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Sektör Kıyaslama</h1>
          <p className={styles.pageSubtitle}>
            Reklam metrikleriniz{' '}
            {data ? data.vertical : 'E-ticaret'} sektör referans
            aralıklarına göre nerede?
          </p>
          <p className={styles.pageNote}>
            Gösterilen değerler referans aralıklarıdır; belirli bir
            sonucu garanti etmez.
          </p>
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <SectionCard>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchBenchmark}>
                Tekrar Dene
              </button>
            </div>
          </SectionCard>
        ) : data ? (
          <>
            {/* Headline banner + summary chips */}
            <div className={styles.headlineBanner}>
              <span className={styles.headlineIcon} aria-hidden="true">
                *
              </span>
              <div style={{ flex: 1 }}>
                <p className={styles.headlineText}>
                  {noData
                    ? 'Kıyaslama için yeterli veri bulunamadı.'
                    : data.headline}
                </p>
                {!noData && (
                  <div className={styles.summaryChips}>
                    <span className={`${styles.chip} ${styles.chipStrong}`}>
                      Güçlü {data.summary_counts.strong}
                    </span>
                    <span style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>
                      ·
                    </span>
                    <span className={`${styles.chip} ${styles.chipAverage}`}>
                      Ortalama {data.summary_counts.average}
                    </span>
                    <span style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>
                      ·
                    </span>
                    <span className={`${styles.chip} ${data.summary_counts.weak === 0 ? styles.chipNeutral : styles.chipWeak}`}>
                      Zayıf {data.summary_counts.weak}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Prioritized insights — what to do, not just where you stand */}
            {!noData && (data.insights?.length ?? 0) > 0 && (
              <InsightsSection insights={data.insights ?? []} />
            )}

            {/* Metrics section */}
            {!noData && data.metrics.length > 0 && (
              <div className={styles.sectionCard}>
                <div className={styles.sectionHeader}>
                  <span className={styles.sectionTitle}>Metrik Detayları</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                    <ZoneLegend />
                    <span className={styles.periodLabel}>
                      {data.period.date_from} — {data.period.date_to}
                    </span>
                  </div>
                </div>
                <div className={styles.metricList}>
                  {data.metrics.map((metric) => (
                    <MetricRow key={metric.key} metric={metric} />
                  ))}
                </div>
              </div>
            )}

            {/* Channels section */}
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Kanal Kıyaslaması</span>
                <button
                  className={styles.csvBtn}
                  onClick={() =>
                    downloadRowsAsCsv(
                      data.channels.map((ch) => ({
                        kanal: ch.label,
                        roas: ch.roas,
                        roas_konumu: POSITION_LABELS[ch.roas_position],
                        ctr: ch.ctr,
                        ctr_konumu: POSITION_LABELS[ch.ctr_position],
                      })),
                      `benchmark-${data.period.date_from}-${data.period.date_to}.csv`,
                      [
                        { key: 'kanal', label: 'Kanal' },
                        { key: 'roas', label: 'ROAS' },
                        { key: 'roas_konumu', label: 'ROAS Konumu' },
                        { key: 'ctr', label: 'CTR' },
                        { key: 'ctr_konumu', label: 'CTR Konumu' },
                      ],
                    )
                  }
                  disabled={data.channels.length === 0}
                >
                  CSV İndir
                </button>
              </div>
              <ChannelsSection channels={data.channels} />
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
