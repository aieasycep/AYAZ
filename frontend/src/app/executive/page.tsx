'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import AppNav from '@/components/AppNav';
import EmptyState from '@/components/EmptyState';
import SectionCard from '@/components/SectionCard';
import {
  getExecutiveOverview,
  type ExecutiveOverview,
  type ExecGoal,
  type ExecInsight,
  type ChannelRoi,
} from '@/lib/executive-api';
import { channelColor } from '@/lib/chartColors';
import { parseApiError } from '@/lib/parseApiError';
import styles from './executive.module.css';

// --- Formatters ---

const tryFmt = new Intl.NumberFormat('tr-TR', {
  style: 'currency',
  currency: 'TRY',
  maximumFractionDigits: 0,
});

function fmtCurrency(n: number): string {
  return tryFmt.format(n);
}

function fmtNumber(n: number): string {
  return n.toLocaleString('tr-TR');
}

function fmtRoas(n: number): string {
  return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + 'x';
}

function fmtDelta(pct: number | null): { text: string; dir: 'up' | 'down' | 'neutral' } {
  if (pct === null || pct === undefined) return { text: '—', dir: 'neutral' };
  const abs = Math.abs(pct).toLocaleString('tr-TR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  if (pct > 0) return { text: `▲ %${abs}`, dir: 'up' };
  if (pct < 0) return { text: `▼ %${abs}`, dir: 'down' };
  return { text: `%${abs}`, dir: 'neutral' };
}

// --- Delta badge ---

function DeltaBadge({ pct }: { pct: number | null }) {
  const { text, dir } = fmtDelta(pct);
  const cls =
    dir === 'up'
      ? styles.deltaUp
      : dir === 'down'
      ? styles.deltaDown
      : styles.deltaNeutral;
  return <span className={`${styles.deltaBadge} ${cls}`}>{text}</span>;
}

// --- Goal status badge ---

const GOAL_STATUS_LABELS: Record<string, string> = {
  on_track: 'Yolunda',
  at_risk: 'Riskli',
  behind: 'Geride',
};

function goalStatusClass(status: string): string {
  switch (status) {
    case 'on_track':
      return styles.goalStatusOnTrack;
    case 'at_risk':
      return styles.goalStatusAtRisk;
    case 'behind':
      return styles.goalStatusBehind;
    default:
      return styles.goalStatusDefault;
  }
}

function goalFillClass(pct: number): string {
  if (pct >= 80) return styles.goalProgressFillGood;
  if (pct >= 50) return styles.goalProgressFillMid;
  return styles.goalProgressFillWeak;
}

// --- Severity badge ---

const SEVERITY_LABELS: Record<string, string> = {
  critical: 'Kritik',
  warning: 'Uyarı',
  info: 'Bilgi',
};

function severityClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return styles.severityCritical;
    case 'warning':
      return styles.severityWarning;
    default:
      return styles.severityInfo;
  }
}

// --- KPI Cards ---

interface KpiCardProps {
  label: string;
  value: string;
  delta: number | null;
  highlight?: boolean;
}

function KpiCard({ label, value, delta, highlight }: KpiCardProps) {
  return (
    <div className={styles.kpiCard}>
      <div className={styles.kpiLabel}>{label}</div>
      <div className={highlight ? styles.kpiValueRoas : styles.kpiValue}>{value}</div>
      <div className={styles.kpiDeltaRow}>
        <DeltaBadge pct={delta} />
        <span className={styles.deltaLabel}>önceki döneme göre</span>
      </div>
    </div>
  );
}

// --- Channel ROI section ---

function ChannelRoiSection({ channels }: { channels: ChannelRoi[] }) {
  const chartData = channels.map((ch) => ({
    label: ch.label,
    roas: ch.roas,
  }));

  return (
    <>
      {channels.length > 0 && (
        <div className={styles.chartWrap}>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart
              data={chartData}
              margin={{ top: 4, right: 12, left: 0, bottom: 0 }}
              barCategoryGap="35%"
            >
              <CartesianGrid
                strokeDasharray="3 3"
                stroke="var(--color-border)"
                vertical={false}
              />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                tickLine={false}
                axisLine={false}
                width={32}
                tickFormatter={(v: number) => `${v}x`}
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 8,
                  border: '1px solid var(--color-border)',
                  fontSize: 12,
                  background: 'var(--color-surface)',
                  color: 'var(--color-text)',
                }}
                formatter={(value: number) => [fmtRoas(value), 'ROAS']}
              />
              <Bar dataKey="roas" radius={[4, 4, 0, 0]} name="roas" isAnimationActive={false}>
                {channels.map((ch) => (
                  <Cell key={ch.channel} fill={channelColor(ch.channel)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div style={{ overflowX: 'auto' }}>
        <table className={styles.channelTable}>
          <thead>
            <tr>
              <th>Kanal</th>
              <th className={styles.numCol}>Harcama</th>
              <th className={styles.numCol}>Gelir</th>
              <th className={styles.numCol}>ROAS</th>
              <th>Pay</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((ch) => (
              <tr key={ch.channel}>
                <td>
                  <span className={styles.channelLabelWrap}>
                    <span
                      className={styles.channelDot}
                      style={{ background: channelColor(ch.channel) }}
                    />
                    <span className={styles.channelLabel}>{ch.label}</span>
                  </span>
                </td>
                <td className={styles.numCol}>{fmtCurrency(ch.spend)}</td>
                <td className={styles.numCol}>{fmtCurrency(ch.revenue)}</td>
                <td className={`${styles.numCol} ${styles.roasValue}`}>
                  {fmtRoas(ch.roas)}
                </td>
                <td>
                  <div className={styles.shareBarWrap}>
                    <div className={styles.shareBarTrack}>
                      <div
                        className={styles.shareBarFill}
                        style={{ width: `${Math.min(ch.share_pct, 100)}%` }}
                      />
                    </div>
                    <span className={styles.shareBarPct}>
                      %{ch.share_pct.toLocaleString('tr-TR', { maximumFractionDigits: 1 })}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// --- Goals section ---

function GoalsSection({ goals }: { goals: ExecGoal[] }) {
  if (goals.length === 0) {
    return (
      <EmptyState
        title="Henüz hedef tanımlanmadı"
        subtitle="Pazarlama hedeflerinizi ekleyerek ilerlemenizi takip edin."
        action={{ label: '+ Hedef ekle', href: '/goals' }}
      />
    );
  }

  return (
    <div className={styles.goalList}>
      {goals.map((goal, idx) => {
        const clampedPct = Math.min(Math.max(goal.pct_to_target, 0), 100);
        return (
          <div key={`${goal.name}-${idx}`} className={styles.goalRow}>
            <div style={{ flex: '1 1 120px', minWidth: 0 }}>
              <div className={styles.goalName}>{goal.name}</div>
              <div className={styles.goalMetric}>{goal.metric}</div>
            </div>
            <div className={styles.goalProgress}>
              <div className={styles.goalProgressTrack}>
                <div
                  className={`${styles.goalProgressFill} ${goalFillClass(clampedPct)}`}
                  style={{ width: `${clampedPct}%` }}
                />
              </div>
              <div className={styles.goalProgressNumbers}>
                <span>
                  {fmtNumber(Math.round(goal.current_value))}
                </span>
                <span>
                  %{clampedPct.toLocaleString('tr-TR', { maximumFractionDigits: 0 })} / Hedef{' '}
                  {fmtNumber(Math.round(goal.target_value))}
                </span>
              </div>
            </div>
            <span
              className={`${styles.goalStatusBadge} ${goalStatusClass(goal.status)}`}
            >
              {GOAL_STATUS_LABELS[goal.status] ?? goal.status}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// --- Insights section ---

function InsightsSection({ insights }: { insights: ExecInsight[] }) {
  if (insights.length === 0) {
    return (
      <div className={styles.stateBox}>
        <span className={styles.muted}>Aktif içgörü yok.</span>
      </div>
    );
  }

  return (
    <div className={styles.insightList}>
      {insights.map((ins, idx) => (
        <div key={idx} className={styles.insightRow}>
          <span
            className={`${styles.severityBadge} ${severityClass(ins.severity)}`}
          >
            {SEVERITY_LABELS[ins.severity] ?? ins.severity}
          </span>
          <div className={styles.insightContent}>
            <div className={styles.insightTitle}>{ins.title}</div>
            {ins.channel && (
              <div className={styles.insightChannel}>{ins.channel}</div>
            )}
          </div>
        </div>
      ))}
    </div>
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
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// --- Main page ---

export default function ExecutivePage() {
  const [data, setData] = useState<ExecutiveOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getExecutiveOverview();
      setData(result);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOverview();
  }, [fetchOverview]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Yönetici Görünümü</h1>
          <p className={styles.pageSubtitle}>
            Pazarlamanın tek bakışta durumu — üst düzey özet.
          </p>
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <SectionCard>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchOverview}>
                Tekrar Dene
              </button>
            </div>
          </SectionCard>
        ) : data ? (
          <>
            {/* Headline banner - keep on top */}
            <div className={styles.headlineBanner}>
              <span className={styles.headlineAiBadge} aria-hidden="true">AI</span>
              <p className={styles.headlineText}>{data.headline}</p>
            </div>

            {/* KPI row */}
            <div className={styles.kpiGrid}>
              <KpiCard
                label="Toplam Harcama"
                value={fmtCurrency(data.kpis.spend)}
                delta={data.kpis.deltas.spend_pct}
              />
              <KpiCard
                label="Toplam Gelir"
                value={fmtCurrency(data.kpis.revenue)}
                delta={data.kpis.deltas.revenue_pct}
              />
              <KpiCard
                label="ROAS"
                value={fmtRoas(data.kpis.roas)}
                delta={data.kpis.deltas.roas_pct}
                highlight
              />
              <KpiCard
                label="Dönüşüm"
                value={fmtNumber(data.kpis.conversions)}
                delta={data.kpis.deltas.conversions_pct}
              />
            </div>

            {/* Channel ROI */}
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Kanal ROI</span>
                <span className={styles.periodLabel}>
                  {data.period.date_from} — {data.period.date_to}
                </span>
              </div>
              {data.channels.length === 0 ? (
                <div className={styles.stateBox}>
                  <span className={styles.muted}>Kanal verisi bulunamadı.</span>
                </div>
              ) : (
                <ChannelRoiSection channels={data.channels} />
              )}
            </div>

            {/* Goals */}
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Hedefler</span>
              </div>
              <GoalsSection goals={data.goals} />
            </div>

            {/* Insights */}
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Öne Çıkan İçgörüler</span>
              </div>
              <InsightsSection insights={data.insights} />
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
