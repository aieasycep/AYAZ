'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  getToken,
  getDashboardSummary,
  getTimeseries,
  type DashboardSummary,
  type TimeseriesResponse,
  type TimeseriesMetric,
} from '@/lib/api';
import KpiCard from '@/components/KpiCard';
import TimeSeriesChart from '@/components/TimeSeriesChart';
import ChannelTable from '@/components/ChannelTable';
import AppNav from '@/components/AppNav';
import DashboardEmptyState from '@/components/DashboardEmptyState';
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

  const defaults = getDefaultDates();
  const [dateFrom, setDateFrom] = useState(defaults.from);
  const [dateTo, setDateTo] = useState(defaults.to);
  const [appliedFrom, setAppliedFrom] = useState(defaults.from);
  const [appliedTo, setAppliedTo] = useState(defaults.to);

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [metric, setMetric] = useState<TimeseriesMetric>('spend');
  const [timeseries, setTimeseries] = useState<TimeseriesResponse | null>(null);
  const [tsLoading, setTsLoading] = useState(true);
  const [tsError, setTsError] = useState<string | null>(null);

  const fetchSummary = useCallback(async (from: string, to: string) => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const data = await getDashboardSummary(from, to);
      setSummary(data);
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
    fetchSummary(appliedFrom, appliedTo);
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
    fetchSummary(dateFrom, dateTo);
    fetchTimeseries(dateFrom, dateTo, metric);
  }

  const totals = summary?.totals;

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
        {/* Empty state — no connected accounts yet */}
        {hasNoData && <DashboardEmptyState />}

        {/* Date range */}
        <section className={styles.dateBar}>
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
        </section>

        {/* KPI cards */}
        <section className={styles.kpiGrid}>
          {summaryLoading ? (
            <div className={styles.kpiPlaceholder}>
              <span className={styles.muted}>KPI verileri yükleniyor...</span>
            </div>
          ) : summaryError ? (
            <div className={styles.kpiPlaceholder}>
              <span className={styles.errorText}>{summaryError}</span>
            </div>
          ) : totals ? (
            <>
              <KpiCard label="Harcama" value={fmtCurrency(totals.spend)} />
              <KpiCard label="Gösterim" value={fmtNum(totals.impressions)} />
              <KpiCard label="Tıklama" value={fmtNum(totals.clicks)} />
              <KpiCard label="Dönüşüm" value={fmtNum(totals.conversions)} />
              <KpiCard label="ROAS" value={fmtRoas(totals.roas)} />
              <KpiCard label="CPC" value={fmtCurrency(totals.cpc, 2)} />
              <KpiCard label="CPA" value={fmtCurrency(totals.cpa, 2)} />
              <KpiCard label="CTR" value={fmtPct(totals.ctr)} />
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
          <TimeSeriesChart
            points={timeseries?.points ?? []}
            metricLabel={metricLabel}
            loading={tsLoading}
            error={tsError}
          />
        </section>

        {/* By-channel table */}
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <h2 className={styles.cardTitle}>Kanala Gore Performans</h2>
          </div>
          <ChannelTable
            rows={summary?.by_channel ?? []}
            loading={summaryLoading}
            error={summaryError}
          />
        </section>
      </main>
    </div>
  );
}
