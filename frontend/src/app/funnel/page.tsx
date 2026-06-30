'use client';

import { useState, useEffect, useCallback } from 'react';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import { getFunnel, type FunnelOverview, type FunnelStage } from '@/lib/funnel-api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './funnel.module.css';

// Below this many total events, percentages are statistically noisy enough
// that a single event can swing a stage's conversion rate by several points.
const SMALL_SAMPLE_THRESHOLD = 100;

// --- Formatters ---

function fmtPct(value: number): string {
  return (
    value.toLocaleString('tr-TR', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }) + '%'
  );
}

function fmtCount(value: number): string {
  return value.toLocaleString('tr-TR');
}

// Below 33% step-to-step conversion, call it out as a weak transition;
// otherwise treat it as a normal/healthy part of the funnel. This keeps the
// chip's color meaningful instead of always-green/always-red noise.
const WEAK_CONVERSION_THRESHOLD = 33;

// --- Loading skeleton ---

function LoadingSkeleton() {
  return (
    <div className={styles.skeletonWrap}>
      <div className={`${styles.skeleton} ${styles.skeletonHero}`} />
      <div className={`${styles.skeleton} ${styles.skeletonFunnel}`} />
    </div>
  );
}

// --- Hero row ---

interface HeroRowProps {
  data: FunnelOverview;
}

function HeroRow({ data }: HeroRowProps) {
  const { overall_conversion_pct, entry_count, final_count, biggest_dropoff } = data;

  return (
    <div className={styles.heroRow}>
      {/* Genel Dönüşüm */}
      <div className={styles.heroStat}>
        <div className={styles.heroStatLabel}>Genel Dönüşüm</div>
        <div className={styles.heroStatValue}>{fmtPct(overall_conversion_pct)}</div>
        <div className={styles.heroStatCaption}>
          {fmtCount(entry_count)} giriş &rarr; {fmtCount(final_count)} satın alma
        </div>
      </div>

      {/* En Büyük Düşüş */}
      {biggest_dropoff ? (
        <div
          className={`${styles.heroStat} ${styles.heroStatWarning}`}
          style={{ background: 'var(--color-warning-bg)', borderColor: 'var(--color-warning)' }}
        >
          <div
            className={styles.heroStatLabel}
            style={{ color: 'var(--color-warning-text)', fontWeight: 800 }}
          >
            EN BÜYÜK DÜŞÜŞ
          </div>
          <div className={`${styles.heroStatValue} ${styles.heroStatValueWarning}`}>
            {fmtPct(biggest_dropoff.dropoff_pct)}
          </div>
          <div className={styles.heroStatCaption}>
            {biggest_dropoff.from_label} &rarr; {biggest_dropoff.to_label}
          </div>
        </div>
      ) : (
        <div className={styles.heroStat}>
          <div className={styles.heroStatLabel}>En Büyük Düşüş</div>
          <div className={styles.heroStatValueMuted}>&mdash;</div>
        </div>
      )}
    </div>
  );
}

// --- Funnel stage row ---

interface StageRowProps {
  stage: FunnelStage;
  isFirst: boolean;
  isLast: boolean;
}

function StageRow({ stage, isFirst, isLast }: StageRowProps) {
  const barWidth = `${Math.max(stage.share_of_entry_pct, 4)}%`;

  return (
    <div className={`${styles.stageRow} ${isLast ? styles.stageRowLast : ''}`}>
      {/* Bar + label area */}
      <div className={styles.stageBarArea}>
        <div className={styles.stageBar} style={{ width: barWidth }}>
          <div className={styles.stageBarInner}>
            <span className={styles.stageLabel}>{stage.label}</span>
          </div>
        </div>

        {/* Stats to the right of bar */}
        <div className={styles.stageStats}>
          <span className={styles.stageCount}>{fmtCount(stage.count)}</span>
          <span className={styles.stageShare}>{fmtPct(stage.share_of_entry_pct)}</span>

          {/* Single, unambiguous metric for this transition: the conversion
              rate from the previous step. Color signals whether it's a weak
              transition — no separate/contradictory dropoff badge. */}
          {!isFirst && stage.conversion_from_prev_pct !== null && (
            <span
              className={`${styles.conversionChip} ${
                stage.conversion_from_prev_pct < WEAK_CONVERSION_THRESHOLD
                  ? styles.conversionChipWeak
                  : ''
              }`}
              title="Önceki adımdan dönüşüm oranı"
            >
              {fmtPct(stage.conversion_from_prev_pct)} geçiş
            </span>
          )}
        </div>
      </div>

      {/* Connector between stages */}
      {!isLast && <div className={styles.stageConnector}><div className={styles.connectorLine} /></div>}
    </div>
  );
}

// --- Funnel visualization ---

interface FunnelVizProps {
  stages: FunnelStage[];
}

function FunnelViz({ stages }: FunnelVizProps) {
  if (stages.length === 0) {
    return (
      <div className={styles.stateBox}>
        <span className={styles.muted}>Huni verisi yok.</span>
      </div>
    );
  }

  return (
    <div className={styles.funnelViz}>
      {stages.map((stage, i) => (
        <StageRow
          key={stage.key}
          stage={stage}
          isFirst={i === 0}
          isLast={i === stages.length - 1}
        />
      ))}
    </div>
  );
}

// --- Main page ---

export default function FunnelPage() {
  const [data, setData] = useState<FunnelOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchFunnel = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getFunnel();
      setData(result);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchFunnel();
  }, [fetchFunnel]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Dönüşüm Hunisi</h1>
          <p className={styles.pageSubtitle}>
            Müşteri yolculuğunun her adımındaki dönüşüm ve düşüşü görün.
          </p>
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <SectionCard>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchFunnel}>
                Tekrar Dene
              </button>
            </div>
          </SectionCard>
        ) : data ? (
          <>
            {/* Small-sample warning — percentages get noisy on low volume */}
            {data.total_events < SMALL_SAMPLE_THRESHOLD && (
              <div className={styles.sampleWarning} role="status">
                <span aria-hidden="true">&#9888;</span>
                Örneklem küçük ({fmtCount(data.total_events)} olay) — yüzdeler yanıltıcı olabilir
              </div>
            )}

            {/* Hero stats */}
            <HeroRow data={data} />

            {/* Funnel section */}
            <SectionCard
              title="Müşteri Yolculuğu"
              right={
                <span className={styles.periodLabel}>
                  {data.period.date_from} &mdash; {data.period.date_to}
                </span>
              }
            >
              <div className={styles.funnelWrap}>
                <FunnelViz stages={data.stages} />
              </div>
            </SectionCard>
          </>
        ) : null}
      </main>
    </div>
  );
}
