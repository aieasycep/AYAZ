'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import AppNav from '@/components/AppNav';
import {
  getCreativeInsights,
  type CreativeLens,
  type CreativeRow,
} from '@/lib/marcom-api';
import styles from './creative-lens.module.css';

// --- Formatters ---

const numFmt = new Intl.NumberFormat('tr-TR');

function fmtNumber(n: number): string {
  return numFmt.format(n);
}

function fmtCtr(ctr: number): string {
  return (
    '%' +
    ctr.toLocaleString('tr-TR', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })
  );
}

function fmtShare(pct: number): string {
  return (
    '%' +
    pct.toLocaleString('tr-TR', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })
  );
}

// --- Loading skeleton ---

function LoadingSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonBanner}`} />
      <div className={styles.skeletonKpiGrid}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={`${styles.skeleton} ${styles.skeletonCard}`} />
        ))}
      </div>
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// --- KPI card ---

interface KpiCardProps {
  label: string;
  value: string;
  highlight?: boolean;
}

function KpiCard({ label, value, highlight }: KpiCardProps) {
  return (
    <div className={styles.kpiCard}>
      <div className={styles.kpiLabel}>{label}</div>
      <div className={highlight ? styles.kpiValueHighlight : styles.kpiValue}>
        {value}
      </div>
    </div>
  );
}

// --- Single creative card ---

function CreativeCard({ row }: { row: CreativeRow }) {
  const shareClamped = Math.min(Math.max(row.traffic_share_pct, 0), 100);

  return (
    <div className={styles.creativeCard}>
      {/* Header: name + channel/campaign */}
      <div className={styles.creativeCardHead}>
        <div className={styles.creativeNameBlock}>
          <div className={styles.creativeName}>{row.ad_name}</div>
          <div className={styles.creativeMeta}>
            <span className={styles.channelBadge}>{row.channel}</span>
            <span className={styles.campaignName}>{row.campaign_name}</span>
          </div>
        </div>
      </div>

      {/* Engagement stats */}
      <div className={styles.statsRow}>
        <div className={styles.statChip}>
          <span className={styles.statChipLabel}>Gösterim</span>
          <span className={styles.statChipValue}>{fmtNumber(row.impressions)}</span>
        </div>
        <div className={styles.statChip}>
          <span className={styles.statChipLabel}>Tıklama</span>
          <span className={styles.statChipValue}>{fmtNumber(row.clicks)}</span>
        </div>
        <div className={styles.statChip}>
          <span className={styles.statChipLabel}>TO</span>
          <span className={styles.statChipValueAccent}>{fmtCtr(row.ctr)}</span>
        </div>
        <div className={styles.statChipWithBar}>
          <span className={styles.statChipLabel}>Trafik Payı</span>
          <div className={styles.shareBarWrap}>
            <div className={styles.shareBarTrack}>
              <div
                className={styles.shareBarFill}
                style={{ width: `${shareClamped}%` }}
              />
            </div>
            <span className={styles.shareBarPct}>{fmtShare(row.traffic_share_pct)}</span>
          </div>
        </div>
      </div>

      {/* Insight */}
      {row.insight && (
        <div className={styles.insightRow}>
          <span className={styles.insightIcon} aria-hidden="true">i</span>
          <span className={styles.insightText}>{row.insight}</span>
        </div>
      )}

      {/* Bridge to content planner */}
      <Link href="/content" className={styles.organicLink}>
        Organik içeriğe çevir &rarr;
      </Link>
    </div>
  );
}

// --- Creatives section ---

function CreativesSection({ creatives }: { creatives: CreativeRow[] }) {
  if (creatives.length === 0) {
    return (
      <div className={styles.stateBox}>
        <span className={styles.muted}>Bu dönemde öne çıkan kreatif bulunamadı.</span>
      </div>
    );
  }

  return (
    <div className={styles.creativeList}>
      {creatives.map((row) => (
        <CreativeCard key={row.ad_id} row={row} />
      ))}
    </div>
  );
}

// --- Main page ---

export default function CreativeLensPage() {
  const [data, setData] = useState<CreativeLens | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getCreativeInsights();
      setData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Kreatif verileri yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Kreatif Lensi</h1>
          <p className={styles.pageSubtitle}>
            Hangi kreatifin ne kadar ilgi ve trafik getirdiğini sade bir dille görün.
          </p>
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
        ) : data ? (
          <>
            {/* Headline banner */}
            <div className={styles.headlineBanner}>
              <span className={styles.headlineIcon} aria-hidden="true">*</span>
              <p className={styles.headlineText}>
                {data.headline || 'Son 30 günün kreatif performans özeti hazır.'}
              </p>
            </div>

            {/* Engagement KPI cards */}
            <div className={styles.kpiGrid}>
              <KpiCard
                label="Toplam Gösterim"
                value={fmtNumber(data.totals.impressions)}
              />
              <KpiCard
                label="Toplam Tıklama"
                value={fmtNumber(data.totals.clicks)}
              />
              <KpiCard
                label="Ortalama TO"
                value={fmtCtr(data.totals.ctr)}
                highlight
              />
              <KpiCard
                label="Kreatif Sayısı"
                value={fmtNumber(data.totals.creatives_count)}
              />
            </div>

            {/* Öne Çıkan Kreatifler */}
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Öne Çıkan Kreatifler</span>
                <span className={styles.periodLabel}>
                  {data.period.date_from} — {data.period.date_to}
                </span>
              </div>
              <CreativesSection creatives={data.top_creatives} />
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
