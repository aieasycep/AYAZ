'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import AppNav from '@/components/AppNav';
import {
  getCommandCenter,
  type CommandCenter,
  type AttentionItem,
  type CcModules,
} from '@/lib/command-center-api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './command-center.module.css';

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
  return (
    n.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

function fmtDelta(pct: number | null): {
  text: string;
  dir: 'up' | 'down' | 'neutral';
} {
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

// --- KPI card ---

interface KpiCardProps {
  label: string;
  value: string;
  delta: number | null;
  highlight?: boolean;
}

function KpiCard({ label, value, delta, highlight }: KpiCardProps) {
  return (
    <div
      className={styles.kpiCard}
      style={highlight ? { borderLeft: '3px solid var(--color-primary)' } : undefined}
    >
      <div className={styles.kpiLabel}>{label}</div>
      <div className={highlight ? styles.kpiValueRoas : styles.kpiValue}>
        {value}
      </div>
      <div className={styles.kpiDeltaRow}>
        <DeltaBadge pct={delta} />
        <span className={styles.deltaLabel}>önceki döneme göre</span>
      </div>
    </div>
  );
}

// --- Attention feed ---

const SEVERITY_LABELS: Record<string, string> = {
  critical: 'Kritik',
  warning: 'Uyarı',
  info: 'Bilgi',
};

// Attention items carry a source-module key; show it with a Turkish label
// (the API value is an internal key like "insights"/"inbox").
const MODULE_LABELS: Record<string, string> = {
  insights: 'İçgörüler',
  inbox: 'Gelen Kutusu',
  content: 'İçerik',
  goals: 'Hedefler',
  budget: 'Bütçe',
  recommendations: 'Öneriler',
  consent: 'KVKK',
  funnel: 'Huni',
};

function severityBadgeClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return styles.severityCritical;
    case 'warning':
      return styles.severityWarning;
    default:
      return styles.severityInfo;
  }
}

function dotClass(severity: string): string {
  switch (severity) {
    case 'critical':
      return styles.dotCritical;
    case 'warning':
      return styles.dotWarning;
    default:
      return styles.dotInfo;
  }
}

function AttentionFeed({ items }: { items: AttentionItem[] }) {
  if (items.length === 0) {
    return (
      <div className={styles.allClearCard}>
        <span className={styles.allClearIcon} aria-hidden="true">
          🎯
        </span>
        <p className={styles.allClearText}>
          Şu an acil dikkat gerektiren bir şey yok.
        </p>
      </div>
    );
  }

  return (
    <div className={styles.attentionList}>
      {items.map((item, idx) => (
        <Link
          key={idx}
          href={item.link}
          className={styles.attentionItem}
        >
          <span
            className={`${styles.attentionDot} ${dotClass(item.severity)}`}
            aria-hidden="true"
          />
          <div className={styles.attentionBody}>
            <div className={styles.attentionTitle}>{item.title}</div>
            {item.detail && item.detail !== item.title && (
              <div className={styles.attentionDetail}>{item.detail}</div>
            )}
          </div>
          <div className={styles.attentionMeta}>
            <span
              className={`${styles.severityBadge} ${severityBadgeClass(item.severity)}`}
            >
              {SEVERITY_LABELS[item.severity] ?? item.severity}
            </span>
            <span className={styles.attentionModule}>
              {MODULE_LABELS[item.module] ?? item.module}
            </span>
            <span className={styles.attentionArrow} aria-hidden="true">
              →
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}

// --- Pace chip ---

function paceChipClass(status: string | null): string {
  switch (status) {
    case 'ahead':
      return styles.paceAhead;
    case 'behind':
      return styles.paceBehind;
    case 'on_track':
      return styles.paceOnTrack;
    default:
      return styles.paceDefault;
  }
}

const PACE_STATUS_LABELS: Record<string, string> = {
  ahead: 'Önde',
  behind: 'Geride',
  on_track: 'Uyumlu',
};

// --- Module status border helper ---

function moduleStatusBorder(
  criticalCount: number,
  warningCount: number,
): React.CSSProperties {
  if (criticalCount > 0) {
    return { borderLeft: '3px solid var(--color-critical)' };
  }
  if (warningCount > 0) {
    return { borderLeft: '3px solid var(--color-warning)' };
  }
  return { borderLeft: '3px solid var(--color-success)' };
}

// --- Module status cards ---

function ModuleCards({ modules }: { modules: CcModules }) {
  return (
    <div className={styles.modulesGrid}>
      {/* Bütçe */}
      <Link
        href="/planning"
        className={styles.moduleCard}
        style={moduleStatusBorder(
          0,
          modules.budget.pace_status === 'behind' ? 1 : 0,
        )}
      >
        <div className={styles.moduleCardHeader}>
          <span className={styles.moduleCardTitle}>Bütçe &amp; Planlama</span>
          <span className={styles.moduleCardArrow} aria-hidden="true">
            →
          </span>
        </div>
        <div className={styles.moduleCardBody}>
          {modules.budget.has_plan ? (
            <>
              {modules.budget.period_month && (
                <div className={styles.moduleStat}>
                  <span className={styles.moduleStatLabel}>Dönem</span>
                  <span className={styles.moduleStatValue}>
                    {modules.budget.period_month}
                  </span>
                </div>
              )}
              {modules.budget.pace_pct !== null && (
                <div className={styles.paceLine}>
                  <span className={styles.pacePct}>
                    %
                    {modules.budget.pace_pct.toLocaleString('tr-TR', {
                      maximumFractionDigits: 0,
                    })}
                  </span>
                  <span className={styles.moduleStatLabel}>harcama temposu</span>
                  {modules.budget.pace_status && (
                    <span
                      className={`${styles.paceChip} ${paceChipClass(modules.budget.pace_status)}`}
                    >
                      {PACE_STATUS_LABELS[modules.budget.pace_status] ??
                        modules.budget.pace_status}
                    </span>
                  )}
                </div>
              )}
            </>
          ) : (
            <span className={styles.noPlan}>Plan yok</span>
          )}
        </div>
      </Link>

      {/* Gelen Kutusu */}
      <Link
        href="/inbox"
        className={styles.moduleCard}
        style={moduleStatusBorder(
          modules.inbox.negative,
          modules.inbox.pending,
        )}
      >
        <div className={styles.moduleCardHeader}>
          <span className={styles.moduleCardTitle}>Gelen Kutusu</span>
          <span className={styles.moduleCardArrow} aria-hidden="true">
            →
          </span>
        </div>
        <div className={styles.moduleCardBody}>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Açık</span>
            <span className={styles.moduleStatValue}>
              {fmtNumber(modules.inbox.open)}
            </span>
          </div>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Bekleyen</span>
            <span className={styles.moduleStatValue}>
              {fmtNumber(modules.inbox.pending)}
            </span>
          </div>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Olumsuz</span>
            <span
              className={
                modules.inbox.negative > 0
                  ? styles.moduleStatValueDanger
                  : styles.moduleStatValue
              }
            >
              {fmtNumber(modules.inbox.negative)}
            </span>
          </div>
        </div>
      </Link>

      {/* İçerik */}
      <Link
        href="/content"
        className={styles.moduleCard}
        style={moduleStatusBorder(
          0,
          modules.content.pending_approval,
        )}
      >
        <div className={styles.moduleCardHeader}>
          <span className={styles.moduleCardTitle}>İçerik</span>
          <span className={styles.moduleCardArrow} aria-hidden="true">
            →
          </span>
        </div>
        <div className={styles.moduleCardBody}>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Taslak</span>
            <span className={styles.moduleStatValue}>
              {fmtNumber(modules.content.draft)}
            </span>
          </div>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Onay bekliyor</span>
            <span
              className={
                modules.content.pending_approval > 0
                  ? styles.moduleStatValueWarning
                  : styles.moduleStatValue
              }
            >
              {fmtNumber(modules.content.pending_approval)}
            </span>
          </div>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Planlandı</span>
            <span className={styles.moduleStatValue}>
              {fmtNumber(modules.content.scheduled)}
            </span>
          </div>
        </div>
      </Link>

      {/* Hedefler */}
      <Link
        href="/goals"
        className={styles.moduleCard}
        style={moduleStatusBorder(
          modules.goals.at_risk,
          0,
        )}
      >
        <div className={styles.moduleCardHeader}>
          <span className={styles.moduleCardTitle}>Hedefler</span>
          <span className={styles.moduleCardArrow} aria-hidden="true">
            →
          </span>
        </div>
        <div className={styles.moduleCardBody}>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Toplam hedef</span>
            <span className={styles.moduleStatValue}>
              {fmtNumber(modules.goals.total)}
            </span>
          </div>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Risk altında</span>
            <span
              className={
                modules.goals.at_risk > 0
                  ? styles.moduleStatValueDanger
                  : styles.moduleStatValue
              }
            >
              {fmtNumber(modules.goals.at_risk)} risk altında
            </span>
          </div>
        </div>
      </Link>

      {/* İçgörüler */}
      <Link
        href="/insights"
        className={styles.moduleCard}
        style={moduleStatusBorder(
          modules.insights.critical,
          modules.insights.warning,
        )}
      >
        <div className={styles.moduleCardHeader}>
          <span className={styles.moduleCardTitle}>İçgörüler</span>
          <span className={styles.moduleCardArrow} aria-hidden="true">
            →
          </span>
        </div>
        <div className={styles.moduleCardBody}>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Kritik</span>
            <span
              className={
                modules.insights.critical > 0
                  ? styles.moduleStatValueDanger
                  : styles.moduleStatValue
              }
            >
              {fmtNumber(modules.insights.critical)}
            </span>
          </div>
          <div className={styles.moduleStat}>
            <span className={styles.moduleStatLabel}>Uyarı</span>
            <span
              className={
                modules.insights.warning > 0
                  ? styles.moduleStatValueWarning
                  : styles.moduleStatValue
              }
            >
              {fmtNumber(modules.insights.warning)}
            </span>
          </div>
        </div>
      </Link>

      {/* Öneriler */}
      <Link
        href="/recommendations"
        className={styles.moduleCard}
        style={moduleStatusBorder(
          0,
          modules.recommendations?.high_impact_open ?? 0,
        )}
      >
        <div className={styles.moduleCardHeader}>
          <span className={styles.moduleCardTitle}>Öneriler</span>
          <span className={styles.moduleCardArrow} aria-hidden="true">
            →
          </span>
        </div>
        <div className={styles.moduleCardBody}>
          {modules.recommendations ? (
            <>
              <div className={styles.moduleStat}>
                <span className={styles.moduleStatLabel}>Açık öneri</span>
                <span className={styles.moduleStatValue}>
                  {fmtNumber(modules.recommendations.open)}
                </span>
              </div>
              <div className={styles.moduleStat}>
                <span className={styles.moduleStatLabel}>Yüksek etkili</span>
                <span
                  className={
                    modules.recommendations.high_impact_open > 0
                      ? styles.moduleStatValueWarning
                      : styles.moduleStatValue
                  }
                >
                  {fmtNumber(modules.recommendations.high_impact_open)}
                </span>
              </div>
            </>
          ) : (
            <span className={styles.noPlan}>—</span>
          )}
        </div>
      </Link>

      {/* KVKK Uyum */}
      <Link
        href="/consent"
        className={styles.moduleCard}
        style={moduleStatusBorder(
          modules.consent && modules.consent.score !== null && modules.consent.score < 60 ? 1 : 0,
          modules.consent && modules.consent.score !== null && modules.consent.score < 80 ? 1 : 0,
        )}
      >
        <div className={styles.moduleCardHeader}>
          <span className={styles.moduleCardTitle}>KVKK Uyum</span>
          <span className={styles.moduleCardArrow} aria-hidden="true">
            →
          </span>
        </div>
        <div className={styles.moduleCardBody}>
          {modules.consent ? (
            <>
              <div className={styles.moduleStat}>
                <span className={styles.moduleStatLabel}>Uyum skoru</span>
                <span className={styles.moduleStatValue}>
                  {modules.consent.score !== null
                    ? `${fmtNumber(modules.consent.score)}/100`
                    : '—'}
                </span>
              </div>
              <div className={styles.moduleStat}>
                <span className={styles.moduleStatLabel}>Durum</span>
                <span className={styles.moduleStatValue}>
                  {modules.consent.grade ?? '—'}
                </span>
              </div>
              <div className={styles.moduleStat}>
                <span className={styles.moduleStatLabel}>Rıza oranı</span>
                <span className={styles.moduleStatValue}>
                  {modules.consent.consent_rate_pct !== null
                    ? `%${modules.consent.consent_rate_pct.toLocaleString('tr-TR', { maximumFractionDigits: 1 })}`
                    : '—'}
                </span>
              </div>
            </>
          ) : (
            <span className={styles.noPlan}>—</span>
          )}
        </div>
      </Link>

      {/* Dönüşüm Hunisi */}
      <Link
        href="/funnel"
        className={styles.moduleCard}
        style={moduleStatusBorder(
          0,
          modules.funnel?.biggest_dropoff_label ? 1 : 0,
        )}
      >
        <div className={styles.moduleCardHeader}>
          <span className={styles.moduleCardTitle}>Dönüşüm Hunisi</span>
          <span className={styles.moduleCardArrow} aria-hidden="true">
            →
          </span>
        </div>
        <div className={styles.moduleCardBody}>
          {modules.funnel ? (
            <>
              <div className={styles.moduleStat}>
                <span className={styles.moduleStatLabel}>Genel dönüşüm</span>
                <span className={styles.moduleStatValue}>
                  {modules.funnel.overall_conversion_pct !== null
                    ? `%${modules.funnel.overall_conversion_pct.toLocaleString('tr-TR', { maximumFractionDigits: 1 })}`
                    : '—'}
                </span>
              </div>
              {modules.funnel.biggest_dropoff_label && (
                <div className={styles.moduleStat}>
                  <span className={styles.moduleStatLabel}>En büyük düşüş</span>
                  <span
                    className={styles.moduleStatValueWarning}
                    style={{ fontSize: '0.775rem', fontWeight: 600 }}
                  >
                    {modules.funnel.biggest_dropoff_label}
                  </span>
                </div>
              )}
            </>
          ) : (
            <span className={styles.noPlan}>—</span>
          )}
        </div>
      </Link>
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
      <div className={styles.skeletonModuleGrid}>
        {[0, 1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className={`${styles.skeleton} ${styles.skeletonModule}`}
          />
        ))}
      </div>
    </>
  );
}

// --- Main page ---

export default function CommandCenterPage() {
  const [data, setData] = useState<CommandCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getCommandCenter();
      setData(result);
    } catch (err: unknown) {
      setError(parseApiError(err));
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
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>Komuta Merkezi</h1>
          <p className={styles.pageSubtitle}>
            Pazarlamanızda şu an önemli olan her şey, tek ekranda.
          </p>
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <div className={styles.sectionCard}>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <button className={styles.retryBtn} onClick={fetchData}>
                Tekrar Dene
              </button>
            </div>
          </div>
        ) : data ? (
          <>
            {/* Headline banner */}
            <div className={styles.headlineBanner}>
              <span className={styles.headlineIcon} aria-hidden="true">
                ◆
              </span>
              <p className={styles.headlineText}>{data.headline}</p>
            </div>

            {/* KPI strip */}
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

            {/* Attention feed */}
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>
                  Dikkat Gerektirenler
                </span>
                {data.attention.length > 0 && (
                  <span className={styles.sectionCount}>
                    {data.attention.length}
                  </span>
                )}
              </div>
              <AttentionFeed items={data.attention} />
            </div>

            {/* Module status cards */}
            <div>
              <div className={styles.moduleSectionHeader}>
                <span className={styles.moduleSectionTitle}>
                  Modül Durumu
                </span>
              </div>
              <ModuleCards modules={data.modules} />
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
