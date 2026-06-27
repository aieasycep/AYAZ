'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getInsights,
  patchInsight,
  generateInsights,
  getAlertRules,
  createAlertRule,
  patchAlertRule,
  deleteAlertRule,
  getInsightFixes,
  applyInsightFix,
  type Insight,
  type InsightSeverity,
  type InsightStatus,
  type AlertRule,
  type AlertComparator,
  type AlertDelivery,
  type InsightFixes,
  type FixAction,
  type FixActionType,
} from '@/lib/insights-api';
import AppNav from '@/components/AppNav';
import ErrorBoundary from '@/components/ErrorBoundary';
import { LoadingState, ErrorState, EmptyState } from '@/components/StateViews';
import styles from './insights.module.css';

// --- Label helpers ---

function severityLabel(s: InsightSeverity): string {
  switch (s) {
    case 'critical': return 'Kritik';
    case 'warning': return 'Uyarı';
    case 'info': return 'Bilgi';
  }
}

function severityClass(s: InsightSeverity): string {
  switch (s) {
    case 'critical': return styles.badgeCritical;
    case 'warning': return styles.badgeWarning;
    case 'info': return styles.badgeInfo;
  }
}

function comparatorLabel(c: AlertComparator): string {
  switch (c) {
    case 'pct_drop': return '% Düşüş';
    case 'pct_rise': return '% Yükseliş';
    case 'below': return 'Altında';
    case 'above': return 'Üzerinde';
    case 'anomaly': return 'Anomali';
  }
}

function deliveryLabel(d: AlertDelivery): string {
  switch (d) {
    case 'email': return 'E-posta';
    case 'slack': return 'Slack';
    case 'none': return 'Bildirim Yok';
  }
}

function fmtDate(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

// --- Fix action label helpers ---

function fixActionIcon(action_type: FixActionType): string {
  switch (action_type) {
    case 'create_alert_rule': return 'Otomatik uyari kurali olustur';
    case 'create_goal':       return 'Hedef koy';
    case 'view_campaign':     return 'Kampanyayi gor';
    case 'dismiss':           return 'Yok say';
  }
}

// --- InsightFixesPanel sub-component ---

interface InsightFixesPanelProps {
  insightId: string;
  onToast: (msg: string) => void;
  onNavigate: (path: string) => void;
}

function InsightFixesPanel({ insightId, onToast, onNavigate }: InsightFixesPanelProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fixes, setFixes] = useState<InsightFixes | null>(null);
  const [applying, setApplying] = useState<Record<string, boolean>>({});
  const [applied, setApplied] = useState<Record<string, boolean>>({});
  const fetchedRef = useRef(false);

  async function handleToggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const data = await getInsightFixes(insightId);
      setFixes(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Cozumler yuklenemedi');
      fetchedRef.current = false; // allow retry
    } finally {
      setLoading(false);
    }
  }

  async function handleApply(fix: FixAction, idx: number) {
    const key = `${idx}`;
    setApplying((prev) => ({ ...prev, [key]: true }));
    try {
      if (fix.action_type === 'view_campaign') {
        onNavigate('/ads');
        return;
      }
      await applyInsightFix(insightId, fix.action_type, fix.payload);
      setApplied((prev) => ({ ...prev, [key]: true }));
      onToast('Olusturuldu');
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : 'Islem basarisiz');
    } finally {
      setApplying((prev) => ({ ...prev, [key]: false }));
    }
  }

  return (
    <div className={styles.fixesExpander}>
      <button
        className={styles.fixesToggleBtn}
        onClick={handleToggle}
      >
        {open ? '▲' : '▼'} Kok neden &amp; cozum
      </button>

      {open && (
        <div className={styles.fixesPanel}>
          {loading ? (
            <div className={styles.fixesLoading}>Yuklenıyor...</div>
          ) : error ? (
            <div className={styles.fixesError}>
              {error}{' '}
              <button
                className={styles.fixesToggleBtn}
                onClick={() => {
                  fetchedRef.current = false;
                  setOpen(false);
                  setTimeout(() => handleToggle(), 0);
                }}
              >
                Tekrar dene
              </button>
            </div>
          ) : fixes ? (
            <>
              <div className={styles.rootCauseLabel}>Kok Neden</div>
              <div className={styles.rootCauseText}>{fixes.root_cause}</div>
              {fixes.fixes.length > 0 && (
                <div className={styles.fixesList}>
                  {fixes.fixes.map((fix, idx) => {
                    const key = `${idx}`;
                    const isDone = applied[key];
                    const isBusy = applying[key];
                    return (
                      <button
                        key={idx}
                        className={`${styles.fixBtn} ${isDone ? styles.fixBtnSuccess : ''}`}
                        onClick={() => handleApply(fix, idx)}
                        disabled={isBusy || isDone}
                        title={fixActionIcon(fix.action_type)}
                      >
                        {isDone ? '✅ ' : ''}{fix.label}
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

// --- Severity filter options ---

type SeverityFilter = InsightSeverity | 'all';
type StatusFilter = InsightStatus | 'all';

const SEVERITY_OPTS: { value: SeverityFilter; label: string }[] = [
  { value: 'all', label: 'Hepsi' },
  { value: 'critical', label: 'Kritik' },
  { value: 'warning', label: 'Uyarı' },
  { value: 'info', label: 'Bilgi' },
];

const STATUS_OPTS: { value: StatusFilter; label: string }[] = [
  { value: 'new', label: 'Yeni' },
  { value: 'seen', label: 'Görüldü' },
  { value: 'all', label: 'Tümü' },
];

// --- Alert rule form state ---

interface RuleFormState {
  name: string;
  metric: string;
  comparator: AlertComparator;
  threshold: string;
  delivery: AlertDelivery;
  destination: string;
  active: boolean;
}

const EMPTY_RULE_FORM: RuleFormState = {
  name: '',
  metric: '',
  comparator: 'pct_drop',
  threshold: '',
  delivery: 'email',
  destination: '',
  active: true,
};

// --- Component ---

export default function InsightsPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  // --- Toast ---
  const [toast, setToast] = useState<string | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showToast(msg: string) {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(msg);
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
  }

  // --- Filters ---
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('new');

  // --- Insights state ---
  const [insights, setInsights] = useState<Insight[]>([]);
  const [insightsLoading, setInsightsLoading] = useState(true);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [actionBusy, setActionBusy] = useState<Record<string, boolean>>({});

  // --- Alert rules state ---
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [rulesError, setRulesError] = useState<string | null>(null);
  const [ruleForm, setRuleForm] = useState<RuleFormState>(EMPTY_RULE_FORM);
  const [ruleSubmitting, setRuleSubmitting] = useState(false);
  const [ruleFormError, setRuleFormError] = useState<string | null>(null);
  const [ruleActionBusy, setRuleActionBusy] = useState<Record<string, boolean>>({});

  // --- Fetch insights ---

  const fetchInsights = useCallback(
    async (sev: SeverityFilter, stat: StatusFilter) => {
      setInsightsLoading(true);
      setInsightsError(null);
      try {
        const data = await getInsights({
          severity: sev === 'all' ? '' : sev,
          status: stat === 'all' ? 'all' : stat,
        });
        // Sort descending by score
        data.sort((a, b) => b.score - a.score);
        setInsights(data);
      } catch (err: unknown) {
        setInsightsError(
          err instanceof Error ? err.message : 'İçgörüler yüklenemedi',
        );
      } finally {
        setInsightsLoading(false);
      }
    },
    [],
  );

  // --- Fetch alert rules ---

  const fetchRules = useCallback(async () => {
    setRulesLoading(true);
    setRulesError(null);
    try {
      const data = await getAlertRules();
      setRules(data);
    } catch (err: unknown) {
      setRulesError(
        err instanceof Error ? err.message : 'Kurallar yüklenemedi',
      );
    } finally {
      setRulesLoading(false);
    }
  }, []);

  // --- Initial load ---

  useEffect(() => {
    if (!getToken()) return;
    fetchInsights(severityFilter, statusFilter);
    fetchRules();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Re-fetch when filters change ---

  useEffect(() => {
    if (!getToken()) return;
    fetchInsights(severityFilter, statusFilter);
  }, [severityFilter, statusFilter, fetchInsights]);

  // --- Generate insights ---

  async function handleGenerate() {
    setGenerating(true);
    try {
      await generateInsights();
      await fetchInsights(severityFilter, statusFilter);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Yenileme başarısız');
    } finally {
      setGenerating(false);
    }
  }

  // --- Insight actions ---

  async function handleInsightAction(id: string, status: InsightStatus) {
    setActionBusy((prev) => ({ ...prev, [id]: true }));
    try {
      const updated = await patchInsight(id, { status });
      setInsights((prev) =>
        prev.map((ins) => (ins.id === updated.id ? updated : ins)),
      );
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'İşlem başarısız');
    } finally {
      setActionBusy((prev) => ({ ...prev, [id]: false }));
    }
  }

  // --- Alert rule submit ---

  async function handleRuleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setRuleFormError(null);

    if (!ruleForm.name.trim()) {
      setRuleFormError('Kural adı zorunludur.');
      return;
    }
    if (!ruleForm.metric.trim()) {
      setRuleFormError('Metrik zorunludur.');
      return;
    }

    const needsThreshold = ruleForm.comparator !== 'anomaly';
    const thresholdNum = parseFloat(ruleForm.threshold);
    if (needsThreshold && (ruleForm.threshold === '' || isNaN(thresholdNum))) {
      setRuleFormError('Bu karşılaştırıcı için eşik değeri zorunludur.');
      return;
    }

    setRuleSubmitting(true);
    try {
      const created = await createAlertRule({
        name: ruleForm.name.trim(),
        metric: ruleForm.metric.trim(),
        comparator: ruleForm.comparator,
        threshold: needsThreshold ? thresholdNum : null,
        delivery: ruleForm.delivery,
        destination: ruleForm.destination.trim() || null,
        active: ruleForm.active,
      });
      setRules((prev) => [...prev, created]);
      setRuleForm(EMPTY_RULE_FORM);
    } catch (err: unknown) {
      setRuleFormError(
        err instanceof Error ? err.message : 'Kural oluşturulamadı',
      );
    } finally {
      setRuleSubmitting(false);
    }
  }

  // --- Alert rule toggle ---

  async function handleRuleToggle(rule: AlertRule) {
    setRuleActionBusy((prev) => ({ ...prev, [rule.id]: true }));
    try {
      const updated = await patchAlertRule(rule.id, { active: !rule.active });
      setRules((prev) =>
        prev.map((r) => (r.id === updated.id ? updated : r)),
      );
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Güncelleme başarısız');
    } finally {
      setRuleActionBusy((prev) => ({ ...prev, [rule.id]: false }));
    }
  }

  // --- Alert rule delete ---

  async function handleRuleDelete(id: string) {
    if (!confirm('Bu kuralı silmek istediğinizden emin misiniz?')) return;
    setRuleActionBusy((prev) => ({ ...prev, [id]: true }));
    try {
      await deleteAlertRule(id);
      setRules((prev) => prev.filter((r) => r.id !== id));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Silme başarısız');
    } finally {
      setRuleActionBusy((prev) => ({ ...prev, [id]: false }));
    }
  }

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>İçgörüler ve Uyarılar</h1>
            <p className={styles.pageSubtitle}>
              Tüm kanallarınızdaki önemli değişimleri ve fırsatları takip edin.
            </p>
          </div>
          <button
            className={styles.refreshBtn}
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating ? 'Yenileniyor...' : 'İçgörüleri Yenile'}
          </button>
        </div>

        {/* Insights section */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>İçgörü Akışı</h2>

            <div className={styles.filterBar}>
              <span className={styles.filterLabel}>Önem:</span>
              {SEVERITY_OPTS.map((opt) => (
                <button
                  key={opt.value}
                  className={`${styles.filterBtn} ${severityFilter === opt.value ? styles.filterBtnActive : ''}`}
                  onClick={() => setSeverityFilter(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
              <span className={styles.filterSep} />
              <span className={styles.filterLabel}>Durum:</span>
              {STATUS_OPTS.map((opt) => (
                <button
                  key={opt.value}
                  className={`${styles.filterBtn} ${statusFilter === opt.value ? styles.filterBtnActive : ''}`}
                  onClick={() => setStatusFilter(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {insightsLoading ? (
            <LoadingState message="İçgörüler yükleniyor..." />
          ) : insightsError ? (
            <ErrorState
              message={insightsError}
              onRetry={() => fetchInsights(severityFilter, statusFilter)}
            />
          ) : insights.length === 0 ? (
            <EmptyState
              title="İçgörü bulunamadı"
              description="Bu filtreler için içgörü bulunamadı."
            />
          ) : (
            <ErrorBoundary label="İçgörü Akışı">
            <div className={styles.feed}>
              {insights.map((ins) => (
                <div
                  key={ins.id}
                  className={`${styles.insightCard} ${ins.status === 'dismissed' ? styles.insightCardDismissed : ''}`}
                >
                  {/* Severity badge */}
                  <div className={styles.severityCol}>
                    <span
                      className={`${styles.badge} ${severityClass(ins.severity)}`}
                    >
                      {severityLabel(ins.severity)}
                    </span>
                  </div>

                  {/* Content */}
                  <div className={styles.insightBody}>
                    <div className={styles.insightTitle}>{ins.title}</div>
                    <div className={styles.insightText}>{ins.body}</div>
                    <div className={styles.insightMeta}>
                      {ins.metric && (
                        <span className={styles.metaChip}>{ins.metric}</span>
                      )}
                      {ins.channel && (
                        <span className={styles.metaChip}>{ins.channel}</span>
                      )}
                      {ins.entity_name && (
                        <span className={styles.metaChip}>
                          {ins.entity_name}
                        </span>
                      )}
                      {ins.period_start && ins.period_end && (
                        <span className={styles.metaChip}>
                          {fmtDate(ins.period_start)} –{' '}
                          {fmtDate(ins.period_end)}
                        </span>
                      )}
                    </div>

                    {/* Root-cause & one-click fix expander */}
                    {ins.status !== 'dismissed' && (
                      <InsightFixesPanel
                        insightId={ins.id}
                        onToast={showToast}
                        onNavigate={(path) => router.push(path)}
                      />
                    )}
                  </div>

                  {/* Actions */}
                  <div className={styles.insightActions}>
                    {ins.status !== 'seen' && ins.status !== 'dismissed' && (
                      <button
                        className={styles.actionBtn}
                        onClick={() => handleInsightAction(ins.id, 'seen')}
                        disabled={actionBusy[ins.id]}
                      >
                        Gördüm
                      </button>
                    )}
                    {ins.status !== 'dismissed' && (
                      <button
                        className={`${styles.actionBtn} ${styles.actionBtnDanger}`}
                        onClick={() =>
                          handleInsightAction(ins.id, 'dismissed')
                        }
                        disabled={actionBusy[ins.id]}
                      >
                        Yok say
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            </ErrorBoundary>
          )}
        </section>

        {/* Alert rules section */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>
              Uyarı Kuralları{rules.length > 0 ? ` (${rules.length})` : ''}
            </h2>
          </div>

          {rulesLoading ? (
            <LoadingState message="Kurallar yükleniyor..." />
          ) : rulesError ? (
            <ErrorState message={rulesError} onRetry={fetchRules} />
          ) : rules.length === 0 ? (
            <EmptyState
              title="Kural yok"
              description="Henüz uyarı kuralı tanımlanmamış."
            />
          ) : (
            <ErrorBoundary label="Uyarı Kuralları">
            <div className={styles.rulesList}>
              {rules.map((rule) => (
                <div key={rule.id} className={styles.ruleRow}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className={styles.ruleName}>{rule.name}</div>
                    <div className={styles.ruleMeta}>
                      {rule.metric} &bull; {comparatorLabel(rule.comparator)}
                      {rule.threshold !== null
                        ? ` ${rule.threshold}`
                        : ''}{' '}
                      &bull; {deliveryLabel(rule.delivery)}
                      {rule.destination ? ` → ${rule.destination}` : ''}
                    </div>
                  </div>
                  <button
                    className={`${styles.ruleToggle} ${rule.active ? styles.ruleToggleActive : styles.ruleToggleInactive}`}
                    onClick={() => handleRuleToggle(rule)}
                    disabled={ruleActionBusy[rule.id]}
                  >
                    {rule.active ? 'Aktif' : 'Pasif'}
                  </button>
                  <button
                    className={styles.ruleDeleteBtn}
                    onClick={() => handleRuleDelete(rule.id)}
                    disabled={ruleActionBusy[rule.id]}
                  >
                    Sil
                  </button>
                </div>
              ))}
            </div>
            </ErrorBoundary>
          )}

          {/* Add rule form */}
          <div className={styles.ruleFormWrapper}>
            <div className={styles.ruleFormTitle}>Yeni Uyarı Kuralı Ekle</div>
            <form onSubmit={handleRuleSubmit}>
              <div className={styles.ruleForm}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Kural Adı</label>
                  <input
                    className={styles.fieldInput}
                    type="text"
                    placeholder="ör. CPC %20 Düşüş"
                    value={ruleForm.name}
                    onChange={(e) =>
                      setRuleForm((f) => ({ ...f, name: e.target.value }))
                    }
                  />
                </div>

                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Metrik</label>
                  <input
                    className={styles.fieldInput}
                    type="text"
                    placeholder="ör. cpc, spend, roas"
                    value={ruleForm.metric}
                    onChange={(e) =>
                      setRuleForm((f) => ({ ...f, metric: e.target.value }))
                    }
                  />
                </div>

                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Karşılaştırıcı</label>
                  <select
                    className={styles.fieldSelect}
                    value={ruleForm.comparator}
                    onChange={(e) =>
                      setRuleForm((f) => ({
                        ...f,
                        comparator: e.target.value as AlertComparator,
                      }))
                    }
                  >
                    <option value="pct_drop">% Düşüş</option>
                    <option value="pct_rise">% Yükseliş</option>
                    <option value="below">Altında</option>
                    <option value="above">Üzerinde</option>
                    <option value="anomaly">Anomali</option>
                  </select>
                </div>

                {ruleForm.comparator !== 'anomaly' && (
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Eşik Değeri</label>
                    <input
                      className={styles.fieldInput}
                      type="number"
                      step="any"
                      placeholder="ör. 20"
                      value={ruleForm.threshold}
                      onChange={(e) =>
                        setRuleForm((f) => ({
                          ...f,
                          threshold: e.target.value,
                        }))
                      }
                    />
                  </div>
                )}

                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Bildirim</label>
                  <select
                    className={styles.fieldSelect}
                    value={ruleForm.delivery}
                    onChange={(e) =>
                      setRuleForm((f) => ({
                        ...f,
                        delivery: e.target.value as AlertDelivery,
                      }))
                    }
                  >
                    <option value="email">E-posta</option>
                    <option value="slack">Slack</option>
                    <option value="none">Bildirim Yok</option>
                  </select>
                </div>

                {ruleForm.delivery !== 'none' && (
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>
                      {ruleForm.delivery === 'email'
                        ? 'E-posta Adresi'
                        : 'Slack Webhook URL'}
                    </label>
                    <input
                      className={styles.fieldInput}
                      type="text"
                      placeholder={
                        ruleForm.delivery === 'email'
                          ? 'ornek@sirket.com'
                          : 'https://hooks.slack.com/...'
                      }
                      value={ruleForm.destination}
                      onChange={(e) =>
                        setRuleForm((f) => ({
                          ...f,
                          destination: e.target.value,
                        }))
                      }
                    />
                  </div>
                )}

                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Durum</label>
                  <div className={styles.fieldToggleRow}>
                    <input
                      type="checkbox"
                      id="rule-active"
                      checked={ruleForm.active}
                      onChange={(e) =>
                        setRuleForm((f) => ({ ...f, active: e.target.checked }))
                      }
                    />
                    <label
                      htmlFor="rule-active"
                      className={styles.fieldToggleLabel}
                    >
                      Aktif
                    </label>
                  </div>
                </div>

                <button
                  type="submit"
                  className={styles.submitBtn}
                  disabled={ruleSubmitting}
                >
                  {ruleSubmitting ? 'Kaydediliyor...' : 'Kural Ekle'}
                </button>
              </div>

              {ruleFormError && (
                <div className={styles.formError}>{ruleFormError}</div>
              )}
            </form>
          </div>
        </section>
      </main>

      {/* Toast notification */}
      {toast && (
        <div className={styles.toast}>
          ✅ {toast}
        </div>
      )}
    </div>
  );
}
