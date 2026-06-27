'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  getToken,
  getDashboardSummary,
  getDashboardSummaryWithCompare,
  getTimeseries,
  downloadCsv,
  type DashboardSummary,
  type DashboardSummaryWithCompare,
  type Deltas,
  type TimeseriesResponse,
  type TimeseriesMetric,
} from '@/lib/api';
import KpiCard from '@/components/KpiCard';
import TimeSeriesChart from '@/components/TimeSeriesChart';
import ChannelTable from '@/components/ChannelTable';
import TopMovers from '@/components/TopMovers';
import AppNav from '@/components/AppNav';
import DashboardEmptyState from '@/components/DashboardEmptyState';
import ErrorBoundary from '@/components/ErrorBoundary';
import { LoadingState, ErrorState } from '@/components/StateViews';
import DateRangePresets, {
  detectPreset,
  type PresetKey,
} from '@/components/DateRangePresets';
import styles from './dashboard.module.css';

// --- Date helpers ---

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getDefaultDates() {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 29);
  return { from: toISODate(from), to: toISODate(to) };
}

const LS_RANGE_KEY = 'ayaz_dashboard_range';

/** Validate that a string looks like YYYY-MM-DD. */
function isValidDate(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s);
}

/** Read the persisted range from localStorage; returns null if absent/invalid. */
function loadPersistedRange(): { from: string; to: string } | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(LS_RANGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed &&
      typeof parsed === 'object' &&
      'from' in parsed &&
      'to' in parsed &&
      isValidDate((parsed as { from: string }).from) &&
      isValidDate((parsed as { to: string }).to)
    ) {
      return { from: (parsed as { from: string }).from, to: (parsed as { to: string }).to };
    }
  } catch {
    // corrupted — ignore
  }
  return null;
}

/** Persist the applied range to localStorage. */
function persistRange(from: string, to: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(LS_RANGE_KEY, JSON.stringify({ from, to }));
  } catch {
    // storage full or blocked — silently ignore
  }
}

// --- Formatters ---

function fmtCurrency(n: number, decimals = 0): string {
  return new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: 'TRY',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function fmtNum(n: number): string {
  return new Intl.NumberFormat('tr-TR').format(Math.round(n));
}

function fmtPct(n: number): string {
  return (
    (n * 100).toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + '%'
  );
}

function fmtRoas(n: number): string {
  return (
    n.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

// --- Metric options ---

const METRIC_OPTIONS: { value: TimeseriesMetric; label: string }[] = [
  { value: 'spend', label: 'Harcama' },
  { value: 'impressions', label: 'Gösterim' },
  { value: 'clicks', label: 'Tıklama' },
  { value: 'conversions', label: 'Dönüşüm' },
  { value: 'roas', label: 'ROAS' },
];

// --- Component ---

export default function DashboardPage() {
  const router = useRouter();

  // Auth guard
  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  // Initialise from persisted range when available, falling back to the
  // 30-day default. All four values derive from the same lazy computation so
  // they stay in sync on the first render.
  const [dateFrom, setDateFrom] = useState<string>(() => {
    const p = loadPersistedRange();
    return p?.from ?? getDefaultDates().from;
  });
  const [dateTo, setDateTo] = useState<string>(() => {
    const p = loadPersistedRange();
    return p?.to ?? getDefaultDates().to;
  });
  const [appliedFrom, setAppliedFrom] = useState<string>(() => {
    const p = loadPersistedRange();
    return p?.from ?? getDefaultDates().from;
  });
  const [appliedTo, setAppliedTo] = useState<string>(() => {
    const p = loadPersistedRange();
    return p?.to ?? getDefaultDates().to;
  });

  // Track which preset is currently active (null = custom/no match)
  const [activePreset, setActivePreset] = useState<PresetKey | null>(() => {
    const p = loadPersistedRange();
    const f = p?.from ?? getDefaultDates().from;
    const t = p?.to ?? getDefaultDates().to;
    return detectPreset(f, t);
  });

  // Compare toggle
  const [compareOn, setCompareOn] = useState(false);

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [compareData, setCompareData] = useState<DashboardSummaryWithCompare | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [metric, setMetric] = useState<TimeseriesMetric>('spend');
  const [timeseries, setTimeseries] = useState<TimeseriesResponse | null>(null);
  const [tsLoading, setTsLoading] = useState(true);
  const [tsError, setTsError] = useState<string | null>(null);

  // CSV export state
  const [csvLoading, setCsvLoading] = useState(false);
  const [csvError, setCsvError] = useState<string | null>(null);

  const fetchSummary = useCallback(async (from: string, to: string, compare: boolean) => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      if (compare) {
        const data = await getDashboardSummaryWithCompare(from, to);
        setSummary(data);
        setCompareData(data);
      } else {
        const data = await getDashboardSummary(from, to);
        setSummary(data);
        setCompareData(null);
      }
    } catch (err: unknown) {
      setSummaryError(err instanceof Error ? err.message : 'Veri alınamadı');
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  const fetchTimeseries = useCallback(
    async (from: string, to: string, m: TimeseriesMetric) => {
      setTsLoading(true);
      setTsError(null);
      try {
        const data = await getTimeseries(from, to, m);
        setTimeseries(data);
      } catch (err: unknown) {
        setTsError(err instanceof Error ? err.message : 'Veri alınamadı');
      } finally {
        setTsLoading(false);
      }
    },
    [],
  );

  // Initial load
  useEffect(() => {
    if (!getToken()) return;
    fetchSummary(appliedFrom, appliedTo, false);
    fetchTimeseries(appliedFrom, appliedTo, metric);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch timeseries when metric changes
  useEffect(() => {
    if (!getToken()) return;
    fetchTimeseries(appliedFrom, appliedTo, metric);
  }, [metric, appliedFrom, appliedTo, fetchTimeseries]);

  function applyDates() {
    setAppliedFrom(dateFrom);
    setAppliedTo(dateTo);
    setActivePreset(detectPreset(dateFrom, dateTo));
    persistRange(dateFrom, dateTo);
    fetchSummary(dateFrom, dateTo, compareOn);
    fetchTimeseries(dateFrom, dateTo, metric);
  }

  function handlePresetSelect(from: string, to: string) {
    // Set inputs and apply immediately — same as picking dates + clicking "Uygula"
    setDateFrom(from);
    setDateTo(to);
    setAppliedFrom(from);
    setAppliedTo(to);
    setActivePreset(detectPreset(from, to));
    persistRange(from, to);
    fetchSummary(from, to, compareOn);
    fetchTimeseries(from, to, metric);
  }

  function handleCompareToggle() {
    const next = !compareOn;
    setCompareOn(next);
    fetchSummary(appliedFrom, appliedTo, next);
  }

  async function handleCsvExport() {
    setCsvLoading(true);
    setCsvError(null);
    try {
      await downloadCsv(
        '/api/v1/dashboard/export',
        { date_from: appliedFrom, date_to: appliedTo },
        `dashboard-${appliedFrom}-${appliedTo}.csv`,
      );
    } catch (err: unknown) {
      setCsvError(err instanceof Error ? err.message : 'Dışa aktarma başarısız');
    } finally {
      setCsvLoading(false);
    }
  }

  const totals = summary?.totals;
  const deltas: Deltas | null = compareData?.deltas ?? null;

  // Detect "no connected accounts" state: data loaded successfully but
  // all channels are empty and spend is exactly zero.
  const hasNoData =
    !summaryLoading &&
    !summaryError &&
    summary !== null &&
    summary.by_channel.length === 0 &&
    (totals?.spend ?? 0) === 0;

  const metricLabel =
    METRIC_OPTIONS.find((m) => m.value === metric)?.label ?? metric;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Empty state -- no connected accounts yet */}
        {hasNoData && <DashboardEmptyState />}

        {/* Date range + compare toggle + CSV export */}
        <section className={styles.dateBar}>
          {/* Quick presets row — spans full width above the inputs */}
          <div className={styles.presetsRow}>
            <DateRangePresets
              onSelect={handlePresetSelect}
              activePreset={activePreset}
            />
          </div>

          <div className={styles.dateGroup}>
            <label className={styles.dateLabel} htmlFor="date-from">
              Başlangıç
            </label>
            <input
              id="date-from"
              type="date"
              className={styles.dateInput}
              value={dateFrom}
              max={dateTo}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </div>
          <div className={styles.dateGroup}>
            <label className={styles.dateLabel} htmlFor="date-to">
              Bitiş
            </label>
            <input
              id="date-to"
              type="date"
              className={styles.dateInput}
              value={dateTo}
              min={dateFrom}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </div>
          <button className={styles.applyBtn} onClick={applyDates}>
            Uygula
          </button>

          {/* Compare toggle */}
          <label className={styles.compareToggle}>
            <input
              type="checkbox"
              className={styles.compareCheckbox}
              checked={compareOn}
              onChange={handleCompareToggle}
            />
            <span className={styles.compareLabel}>Önceki dönemle karşılaştır</span>
          </label>

          {/* CSV export */}
          <div className={styles.csvGroup}>
            <button
              className={styles.csvBtn}
              onClick={handleCsvExport}
              disabled={csvLoading}
            >
              {csvLoading ? 'Indiriliyor...' : 'CSV Indir'}
            </button>
            {csvError && (
              <span className={styles.csvError}>{csvError}</span>
            )}
          </div>
        </section>

        {/* KPI cards */}
        <section className={styles.kpiGrid}>
          {summaryLoading ? (
            <div className={styles.kpiPlaceholder}>
              <LoadingState message="KPI verileri yükleniyor..." />
            </div>
          ) : summaryError ? (
            <div className={styles.kpiPlaceholder}>
              <ErrorState
                message={summaryError}
                onRetry={() => fetchSummary(appliedFrom, appliedTo, compareOn)}
              />
            </div>
          ) : totals ? (
            <>
              <KpiCard
                label="Harcama"
                value={fmtCurrency(totals.spend)}
                delta={compareOn ? deltas?.spend : undefined}
                invertDelta
              />
              <KpiCard
                label="Gösterim"
                value={fmtNum(totals.impressions)}
                delta={compareOn ? deltas?.impressions : undefined}
              />
              <KpiCard
                label="Tıklama"
                value={fmtNum(totals.clicks)}
                delta={compareOn ? deltas?.clicks : undefined}
              />
              <KpiCard
                label="Dönüşüm"
                value={fmtNum(totals.conversions)}
                delta={compareOn ? deltas?.conversions : undefined}
              />
              <KpiCard
                label="ROAS"
                value={fmtRoas(totals.roas)}
                delta={compareOn ? deltas?.roas : undefined}
              />
              <KpiCard
                label="CPC"
                value={fmtCurrency(totals.cpc, 2)}
                delta={compareOn ? deltas?.cpc : undefined}
                invertDelta
              />
              <KpiCard
                label="CPA"
                value={fmtCurrency(totals.cpa, 2)}
                delta={compareOn ? deltas?.cpa : undefined}
                invertDelta
              />
              <KpiCard
                label="CTR"
                value={fmtPct(totals.ctr)}
                delta={compareOn ? deltas?.ctr : undefined}
              />
            </>
          ) : null}
        </section>

        {/* Timeseries chart */}
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <h2 className={styles.cardTitle}>Zaman Serisi</h2>
            <div className={styles.metricPicker}>
              {METRIC_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  className={`${styles.metricBtn} ${metric === opt.value ? styles.metricBtnActive : ''}`}
                  onClick={() => setMetric(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <ErrorBoundary label="Zaman Serisi">
            <TimeSeriesChart
              points={timeseries?.points ?? []}
              metricLabel={metricLabel}
              loading={tsLoading}
              error={tsError}
            />
          </ErrorBoundary>
        </section>

        {/* By-channel table */}
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <h2 className={styles.cardTitle}>Kanala Göre Performans</h2>
          </div>
          <ErrorBoundary label="Kanal Tablosu">
            <ChannelTable
              rows={summary?.by_channel ?? []}
              loading={summaryLoading}
              error={summaryError}
            />
          </ErrorBoundary>
        </section>

        {/* Top Movers widget */}
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <h2 className={styles.cardTitle}>En Çok Değişenler</h2>
          </div>
          <ErrorBoundary label="En Çok Değişenler">
            <TopMovers dateFrom={appliedFrom} dateTo={appliedTo} />
          </ErrorBoundary>
        </section>
      </main>
    </div>
  );
}
