'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getLatestBriefing,
  getBriefings,
  generateBriefing,
  type Briefing,
  type BriefingSummary,
  type TopInsight,
  type GoalStatus,
  type GoalStatusItem,
} from '@/lib/briefing-api';
import { parseApiError } from '@/lib/parseApiError';
import AppNav from '@/components/AppNav';
import EmptyState from '@/components/EmptyState';
import styles from './briefing.module.css';

// --- Formatters ---

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('tr-TR', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  });
}

function fmtPct(pct: number): string {
  const abs = Math.abs(pct);
  return abs.toLocaleString('tr-TR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }) + '%';
}

function fmtNum(n: number): string {
  return n.toLocaleString('tr-TR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

// --- Delta metric display labels ---

const DELTA_LABELS: Record<string, string> = {
  spend: 'Harcama',
  roas: 'ROAS',
  conversions: 'Dönüşüm',
  clicks: 'Tıklama',
  impressions: 'Gösterim',
  cpc: 'TBM',
  cpa: 'EBM',
  ctr: 'TO',
};

// Metrics where a negative pct change is good (e.g. lower cost)
const NEGATIVE_IS_GOOD = new Set(['spend', 'cpc', 'cpa']);

// --- Severity helpers ---

function severityLabel(s: TopInsight['severity']): string {
  switch (s) {
    case 'critical': return 'Kritik';
    case 'warning': return 'Uyarı';
    case 'info': return 'Bilgi';
  }
}

function severityClass(s: TopInsight['severity']): string {
  switch (s) {
    case 'critical': return styles.badgeCritical;
    case 'warning': return styles.badgeWarning;
    case 'info': return styles.badgeInfo;
  }
}

// --- Goal status helpers ---

function goalStatusLabel(s: GoalStatus): string {
  switch (s) {
    case 'on_track': return 'Yolunda';
    case 'at_risk': return 'Risk Altında';
    case 'off_track': return 'Geride';
  }
}

function goalStatusClass(s: GoalStatus): string {
  switch (s) {
    case 'on_track': return styles.badgeOnTrack;
    case 'at_risk': return styles.badgeAtRisk;
    case 'off_track': return styles.badgeBehind;
  }
}

// --- DeltaCard sub-component ---

interface DeltaCardProps {
  metricKey: string;
  value: number;
  prev: number;
  pct: number;
}

function DeltaCard({ metricKey, value, prev, pct }: DeltaCardProps) {
  const label = DELTA_LABELS[metricKey] ?? metricKey.toUpperCase();
  const isNegativeGood = NEGATIVE_IS_GOOD.has(metricKey);
  const up = pct >= 0;
  // For cost metrics, up (higher cost) is bad; for performance, up is good
  const isGood = isNegativeGood ? !up : up;
  const isNeutral = pct === 0;

  let pctClass = styles.deltaNeutral;
  if (!isNeutral) {
    pctClass = isGood ? styles.deltaUp : styles.deltaDown;
  }

  const arrow = isNeutral ? '' : up ? '▲' : '▼';

  return (
    <div className={styles.deltaCard}>
      <span className={styles.deltaLabel}>{label}</span>
      <span className={styles.deltaValue}>{fmtNum(value)}</span>
      <span className={`${styles.deltaPct} ${pctClass}`}>
        {arrow} {fmtPct(Math.abs(pct))}
      </span>
      <span className={styles.deltaPrev}>Önceki: {fmtNum(prev)}</span>
    </div>
  );
}

// --- GoalRow sub-component ---

function GoalRow({ goal }: { goal: GoalStatusItem }) {
  return (
    <div className={styles.goalRow}>
      <div className={styles.goalInfo}>
        <div className={styles.goalName}>{goal.name}</div>
        <div className={styles.goalForecast}>{goal.forecast}</div>
      </div>
      <span className={`${styles.badge} ${goalStatusClass(goal.status)}`}>
        {goalStatusLabel(goal.status)}
      </span>
    </div>
  );
}

// --- Main page ---

export default function BriefingPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [history, setHistory] = useState<BriefingSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const [refreshing, setRefreshing] = useState(false);

  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function showToast(msg: string) {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(msg);
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
  }

  const fetchLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getLatestBriefing();
      setBriefing(data);
    } catch (err: unknown) {
      // A 404 means "no briefing generated yet" — that is an empty state, not an
      // error. Leave briefing null so the friendly Turkish empty-state branch
      // renders instead of surfacing the backend's English "not found" detail.
      if ((err as { status?: number })?.status === 404) {
        setBriefing(null);
        setError(null);
      } else {
        setError(parseApiError(err));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const data = await getBriefings();
      // Sort descending by date
      data.sort(
        (a, b) =>
          new Date(b.briefing_date).getTime() -
          new Date(a.briefing_date).getTime(),
      );
      setHistory(data);
    } catch (err: unknown) {
      setHistoryError(parseApiError(err));
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchLatest();
    fetchHistory();
  }, [fetchLatest, fetchHistory]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      const data = await generateBriefing();
      setBriefing(data);
      // Refresh history list too
      await fetchHistory();
      showToast('Brifing başarıyla oluşturuldu');
    } catch (err: unknown) {
      showToast(parseApiError(err));
    } finally {
      setRefreshing(false);
    }
  }

  // Extract delta entries from briefing body
  const deltaEntries = briefing
    ? (
        Object.entries(briefing.body.performance_delta) as [
          string,
          { value: number; prev: number; pct: number },
        ][]
      ).filter(([, v]) => v != null)
    : [];

  const deltaEntriesTyped: Array<{
    key: string;
    value: number;
    prev: number;
    pct: number;
  }> = deltaEntries.map(([key, v]) => ({ key, ...v }));

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Günlük Brifing</h1>
            <p className={styles.pageSubtitle}>
              Yapay zeka destekli günlük performans özeti ve öneriler.
            </p>
          </div>
          <button
            className={styles.refreshBtn}
            onClick={handleRefresh}
            disabled={refreshing}
          >
            {refreshing ? 'Oluşturuluyor...' : 'Brifingi Yenile'}
          </button>
        </div>

        {/* Main content area */}
        {loading ? (
          <div className={styles.section}>
            <div className={styles.stateBox}>
              <span className={styles.muted}>Brifing yükleniyor...</span>
            </div>
          </div>
        ) : error ? (
          <div className={styles.section}>
            <EmptyState
              title={error}
              subtitle="Yeniden denemek için aşağıdaki butona tıklayın."
              action={{ label: 'Tekrar Dene', onClick: fetchLatest }}
            />
          </div>
        ) : briefing === null ? (
          <div className={styles.section}>
            <EmptyState
              title="Günlük brifing henüz hazırlanmadı."
              subtitle="Yapay zeka destekli günlük özetinizi oluşturmak için butona tıklayın."
              action={{ label: 'Brifing Oluştur / Yenile', onClick: handleRefresh }}
            />
          </div>
        ) : (
          <>
            {/* 1. Hero headline card */}
            <div className={styles.heroCard}>
              <div className={styles.heroTop}>
                <div>
                  <div className={styles.heroDateLabel}>Brifing Tarihi</div>
                  <div className={styles.heroDate}>
                    {fmtDate(briefing.briefing_date)}
                  </div>
                </div>
              </div>
              <div className={styles.heroHeadline}>{briefing.headline}</div>
            </div>

            {/* 2. Performans degisimi */}
            {deltaEntriesTyped.length > 0 && (
              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2 className={styles.sectionTitle}>Performans Değişimi</h2>
                </div>
                <div className={styles.deltaGrid}>
                  {deltaEntriesTyped.map((d) => (
                    <DeltaCard
                      key={d.key}
                      metricKey={d.key}
                      value={d.value}
                      prev={d.prev}
                      pct={d.pct}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* 3. Öne çıkan içgörüler */}
            {briefing.body.top_insights.length > 0 && (
              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2 className={styles.sectionTitle}>
                    Öne Çıkan İçgörüler
                  </h2>
                </div>
                <div className={styles.insightsList}>
                  {briefing.body.top_insights.map((ins, idx) => (
                    <div key={idx} className={styles.insightRow}>
                      <span
                        className={`${styles.badge} ${severityClass(ins.severity)}`}
                      >
                        {severityLabel(ins.severity)}
                      </span>
                      <div className={styles.insightRowTitle}>{ins.title}</div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* 4. Önerilen aksiyon */}
            {briefing.body.top_recommendation && (
              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2 className={styles.sectionTitle}>Önerilen Aksiyon</h2>
                </div>
                <div className={styles.recommendationBox}>
                  <div className={styles.recommendationMessage}>
                    {briefing.body.top_recommendation.message}
                  </div>
                  <div>
                    <div className={styles.recommendationActionLabel}>
                      Önerilen Adım
                    </div>
                    <div className={styles.recommendationAction}>
                      {briefing.body.top_recommendation.suggested_action}
                    </div>
                  </div>
                </div>
              </section>
            )}

            {/* 5. Hedef durumu */}
            {briefing.body.goals_status.length > 0 && (
              <section className={styles.section}>
                <div className={styles.sectionHeader}>
                  <h2 className={styles.sectionTitle}>Hedef Durumu</h2>
                </div>
                <div className={styles.goalsList}>
                  {briefing.body.goals_status.map((goal, idx) => (
                    <GoalRow key={idx} goal={goal} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}

        {/* 6. Geçmiş brifingler */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Geçmiş Brifingler</h2>
          </div>
          <div className={styles.historyDetails}>
            {historyLoading ? (
              <span className={styles.muted}>Geçmiş yükleniyor...</span>
            ) : historyError ? (
              <span className={styles.errorText}>{historyError}</span>
            ) : history.length === 0 ? (
              <span className={styles.muted}>
                Henüz kayıtlı brifing bulunmuyor.
              </span>
            ) : (
              <details>
                <summary className={styles.historySummary}>
                  Brifingleri Göster ({history.length})
                </summary>
                <div className={styles.historyList}>
                  {history.map((item) => (
                    <button
                      key={item.id}
                      className={styles.historyItem}
                      onClick={() => {
                        // History items are read-only summaries;
                        // clicking highlights the date + headline for reference.
                        showToast(
                          `${fmtDate(item.briefing_date)}: ${item.headline}`,
                        );
                      }}
                    >
                      <span className={styles.historyItemDate}>
                        {fmtDate(item.briefing_date)}
                      </span>
                      <span className={styles.historyItemHeadline}>
                        {item.headline}
                      </span>
                    </button>
                  ))}
                </div>
              </details>
            )}
          </div>
        </section>
      </main>

      {/* Toast notification */}
      {toast && <div className={styles.toast}>{toast}</div>}
    </div>
  );
}
