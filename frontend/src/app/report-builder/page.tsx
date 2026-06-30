'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { getToken } from '@/lib/api';
import {
  buildReport,
  saveReportDefinition,
  type BuildReportResponse,
} from '@/lib/report-builder-api';
import KpiCard from '@/components/KpiCard';
import TimeSeriesChart from '@/components/TimeSeriesChart';
import ChannelTable from '@/components/ChannelTable';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import type { ChannelRow } from '@/lib/api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './report-builder.module.css';

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

// Format a metric value by key name heuristic
function fmtMetricValue(key: string, val: number): string {
  if (key === 'roas') return fmtRoas(val);
  if (key === 'ctr') return fmtPct(val);
  if (key === 'spend' || key === 'cpc' || key === 'cpa' || key === 'conversion_value')
    return fmtCurrency(val, key === 'spend' ? 0 : 2);
  return fmtNum(val);
}

// Human-readable metric labels
const METRIC_LABELS: Record<string, string> = {
  spend: 'Harcama',
  impressions: 'Gösterim',
  clicks: 'Tıklama',
  conversions: 'Dönüşüm',
  roas: 'ROAS',
  cpc: 'CPC',
  cpa: 'CPA',
  ctr: 'CTR',
  conversion_value: 'Dönüşüm Değeri',
};

// --- Example chips ---

const EXAMPLE_CHIPS = [
  'Meta vs Google son 30 gün',
  'TikTok ROAS trendi',
  'Bu ay tüm kanalların özeti',
  'En çok dönüşüm getiren kanal',
];

// --- Prompt hint icon ---

function PromptHintIcon() {
  return (
    <svg
      className={styles.promptHintIcon}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

// --- Component ---

export default function ReportBuilderPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  const defaults = getDefaultDates();
  const [prompt, setPrompt] = useState('');
  const [dateFrom, setDateFrom] = useState(defaults.from);
  const [dateTo, setDateTo] = useState(defaults.to);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<BuildReportResponse | null>(null);

  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  }, []);

  async function handleSubmit() {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const result = await buildReport({
        prompt: trimmed,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      });
      setReport(result);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!report) return;
    setSaving(true);
    try {
      await saveReportDefinition({
        name: report.spec.title,
        config: {
          metrics: report.spec.metrics,
          channels: report.spec.channels,
        },
      });
      showToast('Rapor kaydedildi');
    } catch (err: unknown) {
      showToast(parseApiError(err));
    } finally {
      setSaving(false);
    }
  }

  function handleChip(chip: string) {
    setPrompt(chip);
  }

  // Derive KPI cards: only show metrics in spec.metrics
  const kpiEntries: { label: string; value: string }[] = [];
  if (report) {
    const { spec, data } = report;
    const metricsToShow = spec.metrics.length > 0 ? spec.metrics : Object.keys(data.totals);
    for (const key of metricsToShow) {
      const val = data.totals[key];
      if (val !== undefined) {
        kpiEntries.push({
          label: METRIC_LABELS[key] ?? key,
          value: fmtMetricValue(key, val),
        });
      }
    }
  }

  // Derive channel table rows filtered to spec.channels
  let channelRows: ChannelRow[] = [];
  if (report) {
    const { spec, data } = report;
    const rows = spec.channels.length > 0
      ? data.by_channel.filter((r) => spec.channels.includes(r.channel))
      : data.by_channel;
    channelRows = rows.map((r) => ({
      channel: r.channel,
      spend: r.spend ?? 0,
      impressions: r.impressions ?? 0,
      clicks: r.clicks ?? 0,
      conversions: r.conversions ?? 0,
      conversion_value: (r.conversion_value as number | undefined) ?? 0,
      roas: r.roas ?? 0,
      cpc: r.cpc ?? 0,
      cpa: (r.cpa as number | undefined) ?? 0,
      ctr: r.ctr ?? 0,
    }));
  }

  const tsPoints = report?.data.timeseries ?? [];

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>Rapor Oluşturucu</h1>
          <p className={styles.pageSubtitle}>
            Doğal dille istediğin raporu oluştur
          </p>
        </div>

        {/* Query card */}
        <div className={styles.queryCard}>
          <label className={styles.queryLabel}>Ne görmek istersin?</label>

          <div className={styles.queryRow}>
            <input
              className={styles.queryInput}
              type="text"
              placeholder="Örn: Meta vs Google son 30 gün karşılaştırması"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              disabled={loading}
            />
            <button
              className={styles.submitBtn}
              onClick={handleSubmit}
              disabled={loading || !prompt.trim()}
            >
              {loading ? 'Oluşturuluyor...' : 'Oluştur'}
            </button>
          </div>

          <div className={styles.chipsRow}>
            <span className={styles.chipsLabel}>Örnek:</span>
            {EXAMPLE_CHIPS.map((chip) => (
              <button
                key={chip}
                className={styles.chip}
                onClick={() => handleChip(chip)}
                disabled={loading}
              >
                {chip}
              </button>
            ))}
          </div>

          <div className={styles.dateBar}>
            <div className={styles.dateGroup}>
              <label className={styles.dateLabel} htmlFor="rb-date-from">
                Başlangıç
              </label>
              <input
                id="rb-date-from"
                type="date"
                className={styles.dateInput}
                value={dateFrom}
                max={dateTo}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div className={styles.dateGroup}>
              <label className={styles.dateLabel} htmlFor="rb-date-to">
                Bitiş
              </label>
              <input
                id="rb-date-to"
                type="date"
                className={styles.dateInput}
                value={dateTo}
                min={dateFrom}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* Loading */}
        {loading && (
          <div className={styles.stateBox}>
            <span className={styles.muted}>Rapor oluşturuluyor...</span>
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div className={styles.stateBox}>
            <span className={styles.errorText}>{error}</span>
          </div>
        )}

        {/* Empty / initial state — interactive prompt */}
        {!loading && !error && !report && (
          <SectionCard>
            <div className={styles.promptHint}>
              <div className={styles.promptHintIconWrap}>
                <PromptHintIcon />
              </div>
              <div className={styles.promptHintTitle}>Sorunuzu yazın, rapor hazır</div>
              <div className={styles.promptHintSub}>
                Doğal Türkçe ile aşağıdaki örneklerden birini seçin ya da kendiniz yazın — rapor saniyeler içinde hazırlanır.
              </div>
              <div className={styles.promptHintChips}>
                {EXAMPLE_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    className={styles.promptHintChip}
                    onClick={() => {
                      handleChip(chip);
                    }}
                  >
                    {chip}
                  </button>
                ))}
              </div>
            </div>
          </SectionCard>
        )}

        {/* Generated report */}
        {!loading && !error && report && (
          <div className={styles.reportSection}>
            {/* Title + save button */}
            <div className={styles.reportTitleRow}>
              <h2 className={styles.reportTitle}>{report.spec.title}</h2>
              <button
                className={styles.saveBtn}
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? 'Kaydediliyor...' : 'Raporu Kaydet'}
              </button>
            </div>

            {/* KPI cards */}
            {kpiEntries.length > 0 && (
              <div className={styles.kpiGrid}>
                {kpiEntries.map((entry) => (
                  <KpiCard key={entry.label} label={entry.label} value={entry.value} />
                ))}
              </div>
            )}

            {/* Timeseries chart */}
            {tsPoints.length > 0 && (
              <SectionCard title="Zaman Serisi">
                <TimeSeriesChart
                  points={tsPoints}
                  metricLabel={
                    report.spec.metrics[0]
                      ? (METRIC_LABELS[report.spec.metrics[0]] ?? report.spec.metrics[0])
                      : 'Değer'
                  }
                  loading={false}
                  error={null}
                />
              </SectionCard>
            )}

            {/* Channel table */}
            <SectionCard title="Kanala Göre Performans">
              <ChannelTable
                rows={channelRows}
                loading={false}
                error={null}
              />
            </SectionCard>
          </div>
        )}
      </main>

      {/* Toast */}
      {toast && (
        <div className={styles.toast}>
          {toast}
          <Link href="/reports" className={styles.toastLink}>
            Raporlar
          </Link>
        </div>
      )}
    </div>
  );
}
