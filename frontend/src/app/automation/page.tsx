'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getAutomationRules,
  createAutomationRule,
  patchAutomationRule,
  deleteAutomationRule,
  runAutomationRule,
  getAutomationRuleRuns,
  type AutomationRule,
  type AutomationScope,
  type AutomationMetric,
  type AutomationComparator,
  type AutomationAction,
  type RunResult,
  type RuleRun,
} from '@/lib/automation-api';
import AppNav from '@/components/AppNav';
import EmptyState from '@/components/EmptyState';
import SuggestionsStrip from '@/components/SuggestionsStrip';
import { parseApiError } from '@/lib/parseApiError';
import styles from './automation.module.css';

// ---------------------------------------------------------------------------
// Label helpers
// ---------------------------------------------------------------------------

function scopeLabel(s: AutomationScope): string {
  switch (s) {
    case 'account': return 'Hesap';
    case 'channel': return 'Kanal';
    case 'campaign': return 'Kampanya';
  }
}

function metricLabel(m: AutomationMetric): string {
  switch (m) {
    case 'spend': return 'Harcama';
    case 'roas': return 'ROAS';
    case 'ctr': return 'CTR';
    case 'cpc': return 'CPC';
    case 'cpa': return 'CPA';
    case 'conversions': return 'Dönüşüm';
  }
}

function comparatorLabel(c: AutomationComparator): string {
  switch (c) {
    case 'pct_drop': return '% düşüş';
    case 'pct_rise': return '% artış';
    case 'below': return 'altına düşerse';
    case 'above': return 'üzerine çıkarsa';
    case 'anomaly': return 'anomali tespit edilirse';
  }
}

function actionLabel(a: AutomationAction): string {
  switch (a) {
    case 'alert': return 'Uyarı oluştur';
    case 'notify_email': return 'E-posta bildirimi gönder';
    case 'notify_slack': return 'Slack bildirimi gönder';
    case 'pause_suggest': return 'Duraklatma öner';
  }
}

/**
 * Build the human-readable Turkish rule summary sentence.
 * e.g. "Google Ads kanalında ROAS son 7 günde %20 düşerse → Uyarı oluştur"
 */
function buildRuleSentence(
  scope: AutomationScope,
  scopeFilter: string,
  metric: AutomationMetric,
  comparator: AutomationComparator,
  threshold: string,
  windowDays: number | string,
  action: AutomationAction,
): string {
  const scopePart =
    scope === 'account'
      ? 'Hesap genelinde'
      : scopeFilter
      ? `${scopeFilter} ${scopeLabel(scope).toLowerCase()}ında`
      : `${scopeLabel(scope)} genelinde`;

  const metricPart = metricLabel(metric);
  const windowPart = `son ${windowDays || '?'} günde`;

  let condPart: string;
  if (comparator === 'anomaly') {
    condPart = `${metricPart} için anomali tespit edilirse`;
  } else if (comparator === 'pct_drop' || comparator === 'pct_rise') {
    const pct = threshold ? `%${threshold}` : '%?';
    condPart = `${metricPart} ${windowPart} ${pct} ${comparatorLabel(comparator)}`;
  } else {
    // below / above
    const val = threshold || '?';
    condPart = `${metricPart} ${val} ${comparatorLabel(comparator)}`;
  }

  return `${scopePart} ${condPart} → ${actionLabel(action)}`;
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// Backend run `detail` is a structured object; the error path is a plain string.
// Render a readable summary instead of crashing on an object child.
function fmtRunDetail(detail: Record<string, unknown> | string | null | undefined): string {
  if (detail == null) return '';
  if (typeof detail === 'string') return detail;
  const matched = detail['matched_entities'];
  if (Array.isArray(matched)) {
    return matched.length > 0
      ? `${matched.length} öğe eşleşti`
      : 'Eşleşen öğe yok';
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return '';
  }
}

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------

interface RuleFormState {
  name: string;
  scope: AutomationScope;
  scope_filter: string;
  metric: AutomationMetric;
  comparator: AutomationComparator;
  threshold: string;
  window_days: string;
  action: AutomationAction;
  // action_config fields
  recipients: string;   // for notify_email (comma-separated)
  webhook: string;      // for notify_slack
  message: string;      // optional custom message
  is_active: boolean;
}

const EMPTY_FORM: RuleFormState = {
  name: '',
  scope: 'account',
  scope_filter: '',
  metric: 'roas',
  comparator: 'pct_drop',
  threshold: '',
  window_days: '7',
  action: 'alert',
  recipients: '',
  webhook: '',
  message: '',
  is_active: true,
};

function buildActionConfig(
  action: AutomationAction,
  form: RuleFormState,
): Record<string, string> | null {
  if (action === 'notify_email') {
    return { recipients: form.recipients.trim() };
  }
  if (action === 'notify_slack') {
    const cfg: Record<string, string> = { webhook: form.webhook.trim() };
    if (form.message.trim()) cfg.message = form.message.trim();
    return cfg;
  }
  if (form.message.trim()) {
    return { message: form.message.trim() };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Per-rule UI state (run result + runs history)
// ---------------------------------------------------------------------------

interface RuleUIState {
  runLoading: boolean;
  runResult: RunResult | null;
  runsOpen: boolean;
  runsLoading: boolean;
  runsError: string | null;
  runs: RuleRun[];
}

function emptyUIState(): RuleUIState {
  return {
    runLoading: false,
    runResult: null,
    runsOpen: false,
    runsLoading: false,
    runsError: null,
    runs: [],
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AutomationPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) router.replace('/login');
  }, [router]);

  // --- Rules list state ---
  const [rules, setRules] = useState<AutomationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // --- Per-rule busy flags (toggle, delete) ---
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  // --- Per-rule UI state ---
  const [ruleUI, setRuleUI] = useState<Record<string, RuleUIState>>({});

  // --- Form visibility & state ---
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<RuleFormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Fetch rules
  // ---------------------------------------------------------------------------

  const fetchRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAutomationRules();
      setRules(data);
      // Initialise UI state for any new rule IDs
      setRuleUI((prev) => {
        const next = { ...prev };
        for (const r of data) {
          if (!next[r.id]) next[r.id] = emptyUIState();
        }
        return next;
      });
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchRules();
  }, [fetchRules]);

  // ---------------------------------------------------------------------------
  // Helpers to mutate ruleUI
  // ---------------------------------------------------------------------------

  function setUI(id: string, patch: Partial<RuleUIState>) {
    setRuleUI((prev) => ({
      ...prev,
      [id]: { ...(prev[id] ?? emptyUIState()), ...patch },
    }));
  }

  // ---------------------------------------------------------------------------
  // Toggle is_active
  // ---------------------------------------------------------------------------

  async function handleToggle(rule: AutomationRule) {
    setBusy((prev) => ({ ...prev, [rule.id]: true }));
    try {
      const updated = await patchAutomationRule(rule.id, {
        is_active: !rule.is_active,
      });
      setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    } catch (err: unknown) {
      alert(parseApiError(err));
    } finally {
      setBusy((prev) => ({ ...prev, [rule.id]: false }));
    }
  }

  // ---------------------------------------------------------------------------
  // Delete
  // ---------------------------------------------------------------------------

  async function handleDelete(id: string) {
    if (!confirm('Bu kuralı silmek istediğinizden emin misiniz?')) return;
    setBusy((prev) => ({ ...prev, [id]: true }));
    try {
      await deleteAutomationRule(id);
      setRules((prev) => prev.filter((r) => r.id !== id));
      setRuleUI((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    } catch (err: unknown) {
      alert(parseApiError(err));
    } finally {
      setBusy((prev) => ({ ...prev, [id]: false }));
    }
  }

  // ---------------------------------------------------------------------------
  // Run now
  // ---------------------------------------------------------------------------

  async function handleRun(id: string) {
    setUI(id, { runLoading: true, runResult: null });
    try {
      const result = await runAutomationRule(id);
      setUI(id, { runLoading: false, runResult: result });
    } catch (err: unknown) {
      setUI(id, {
        runLoading: false,
        runResult: {
          triggered: false,
          detail: parseApiError(err),
        },
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Runs history
  // ---------------------------------------------------------------------------

  async function handleToggleRuns(id: string) {
    const ui = ruleUI[id] ?? emptyUIState();
    if (ui.runsOpen) {
      setUI(id, { runsOpen: false });
      return;
    }
    // Open and load
    setUI(id, { runsOpen: true, runsLoading: true, runsError: null });
    try {
      const runs = await getAutomationRuleRuns(id);
      setUI(id, { runsLoading: false, runs });
    } catch (err: unknown) {
      setUI(id, {
        runsLoading: false,
        runsError: parseApiError(err),
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Form submit
  // ---------------------------------------------------------------------------

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    if (!form.name.trim()) {
      setFormError('Kural adı zorunludur.');
      return;
    }
    const needsThreshold = form.comparator !== 'anomaly';
    const thresholdNum = parseFloat(form.threshold);
    if (needsThreshold && (form.threshold === '' || isNaN(thresholdNum))) {
      setFormError('Bu karşılaştırıcı için eşik değeri zorunludur.');
      return;
    }
    const windowNum = parseInt(form.window_days, 10);
    if (isNaN(windowNum) || windowNum < 1) {
      setFormError('Pencere gün sayısı en az 1 olmalıdır.');
      return;
    }
    if (form.action === 'notify_email' && !form.recipients.trim()) {
      setFormError('E-posta bildirimi için alıcı adresi zorunludur.');
      return;
    }
    if (form.action === 'notify_slack' && !form.webhook.trim()) {
      setFormError('Slack bildirimi için webhook URL zorunludur.');
      return;
    }

    setSubmitting(true);
    try {
      const created = await createAutomationRule({
        name: form.name.trim(),
        scope: form.scope,
        scope_filter: form.scope_filter.trim() || null,
        metric: form.metric,
        comparator: form.comparator,
        threshold: needsThreshold ? thresholdNum : null,
        window_days: windowNum,
        action: form.action,
        action_config: buildActionConfig(form.action, form),
        is_active: form.is_active,
      });
      setRules((prev) => [created, ...prev]);
      setRuleUI((prev) => ({ ...prev, [created.id]: emptyUIState() }));
      setForm(EMPTY_FORM);
      setShowForm(false);
    } catch (err: unknown) {
      setFormError(
        parseApiError(err),
      );
    } finally {
      setSubmitting(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Live preview sentence
  // ---------------------------------------------------------------------------

  const previewSentence = buildRuleSentence(
    form.scope,
    form.scope_filter,
    form.metric,
    form.comparator,
    form.threshold,
    form.window_days || '?',
    form.action,
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Otomasyon Kuralları</h1>
            <p className={styles.pageSubtitle}>
              Metrik koşullarına göre otomatik uyarılar ve öneriler tanımlayın.
            </p>
          </div>
          <button
            className={styles.newRuleBtn}
            onClick={() => {
              setShowForm((v) => !v);
              setFormError(null);
              if (!showForm) setForm(EMPTY_FORM);
            }}
          >
            {showForm ? 'Formu Kapat' : 'Yeni Kural'}
          </button>
        </div>

        {/* New rule form */}
        {showForm && (
          <section className={styles.formSection}>
            <div className={styles.formHeader}>
              <span className={styles.formTitle}>Yeni Otomasyon Kuralı</span>
              <button
                className={styles.closeFormBtn}
                onClick={() => setShowForm(false)}
              >
                Kapat
              </button>
            </div>

            <div className={styles.formBody}>
              <form onSubmit={handleSubmit}>
                <div className={styles.formGrid}>
                  {/* Kural adı */}
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Kural Adı</label>
                    <input
                      className={styles.fieldInput}
                      type="text"
                      placeholder="ör. ROAS Düşüş Alarmı"
                      value={form.name}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, name: e.target.value }))
                      }
                    />
                  </div>

                  {/* Kapsam */}
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Kapsam</label>
                    <select
                      className={styles.fieldSelect}
                      value={form.scope}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          scope: e.target.value as AutomationScope,
                          scope_filter: '',
                        }))
                      }
                    >
                      <option value="account">Hesap</option>
                      <option value="channel">Kanal</option>
                      <option value="campaign">Kampanya</option>
                    </select>
                  </div>

                  {/* Kapsam filtresi */}
                  {form.scope !== 'account' && (
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        {form.scope === 'channel'
                          ? 'Kanal Adı'
                          : 'Kampanya Adı / ID'}
                      </label>
                      <input
                        className={styles.fieldInput}
                        type="text"
                        placeholder={
                          form.scope === 'channel'
                            ? 'ör. Google Ads'
                            : 'ör. Yaz Kampanyası'
                        }
                        value={form.scope_filter}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            scope_filter: e.target.value,
                          }))
                        }
                      />
                    </div>
                  )}

                  {/* Metrik */}
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Metrik</label>
                    <select
                      className={styles.fieldSelect}
                      value={form.metric}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          metric: e.target.value as AutomationMetric,
                        }))
                      }
                    >
                      <option value="spend">Harcama</option>
                      <option value="roas">ROAS</option>
                      <option value="ctr">CTR</option>
                      <option value="cpc">CPC</option>
                      <option value="cpa">CPA</option>
                      <option value="conversions">Dönüşüm</option>
                    </select>
                  </div>

                  {/* Karşılaştırıcı */}
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Koşul</label>
                    <select
                      className={styles.fieldSelect}
                      value={form.comparator}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          comparator: e.target.value as AutomationComparator,
                          threshold: '',
                        }))
                      }
                    >
                      <option value="pct_drop">% Düşüş</option>
                      <option value="pct_rise">% Artış</option>
                      <option value="below">Altında</option>
                      <option value="above">Üzerinde</option>
                      <option value="anomaly">Anomali</option>
                    </select>
                  </div>

                  {/* Eşik */}
                  {form.comparator !== 'anomaly' && (
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        {form.comparator === 'pct_drop' ||
                        form.comparator === 'pct_rise'
                          ? 'Eşik (%)'
                          : 'Eşik Değeri'}
                      </label>
                      <input
                        className={styles.fieldInput}
                        type="number"
                        step="any"
                        min="0"
                        placeholder="ör. 20"
                        value={form.threshold}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, threshold: e.target.value }))
                        }
                      />
                    </div>
                  )}

                  {/* Pencere gün sayısı */}
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Pencere (Gün)</label>
                    <input
                      className={styles.fieldInput}
                      type="number"
                      min="1"
                      step="1"
                      placeholder="ör. 7"
                      value={form.window_days}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, window_days: e.target.value }))
                      }
                    />
                  </div>

                  {/* Aksiyon */}
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Aksiyon</label>
                    <select
                      className={styles.fieldSelect}
                      value={form.action}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          action: e.target.value as AutomationAction,
                          recipients: '',
                          webhook: '',
                          message: '',
                        }))
                      }
                    >
                      <option value="alert">Uyarı Oluştur</option>
                      <option value="notify_email">E-posta Bildirimi</option>
                      <option value="notify_slack">Slack Bildirimi</option>
                      <option value="pause_suggest">Duraklatma Öner</option>
                    </select>
                  </div>

                  {/* action_config: e-posta alıcıları */}
                  {form.action === 'notify_email' && (
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Alıcılar (virgülle ayırın)
                      </label>
                      <input
                        className={styles.fieldInput}
                        type="text"
                        placeholder="ali@firma.com, ayse@firma.com"
                        value={form.recipients}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            recipients: e.target.value,
                          }))
                        }
                      />
                    </div>
                  )}

                  {/* action_config: slack webhook */}
                  {form.action === 'notify_slack' && (
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Slack Webhook URL
                      </label>
                      <input
                        className={styles.fieldInput}
                        type="text"
                        placeholder="https://hooks.slack.com/..."
                        value={form.webhook}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, webhook: e.target.value }))
                        }
                      />
                    </div>
                  )}

                  {/* action_config: özel mesaj (opsiyonel, alert/pause_suggest) */}
                  {(form.action === 'alert' ||
                    form.action === 'pause_suggest') && (
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>
                        Özel Mesaj (isteğe bağlı)
                      </label>
                      <input
                        className={styles.fieldInput}
                        type="text"
                        placeholder="ör. Ekip liderine bildirin"
                        value={form.message}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, message: e.target.value }))
                        }
                      />
                    </div>
                  )}

                  {/* Aktif */}
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Durum</label>
                    <div className={styles.fieldToggleRow}>
                      <input
                        type="checkbox"
                        id="auto-active"
                        checked={form.is_active}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            is_active: e.target.checked,
                          }))
                        }
                      />
                      <label
                        htmlFor="auto-active"
                        className={styles.fieldToggleLabel}
                      >
                        Aktif
                      </label>
                    </div>
                  </div>

                  {/* Live preview — spans full width */}
                  <div className={styles.previewBox}>
                    <div className={styles.previewLabel}>Kural Önizlemesi</div>
                    {previewSentence}
                  </div>
                </div>

                {/* Form actions */}
                <div className={styles.formActions}>
                  <button
                    type="submit"
                    className={styles.submitBtn}
                    disabled={submitting}
                  >
                    {submitting ? 'Kaydediliyor...' : 'Kuralı Kaydet'}
                  </button>
                  <button
                    type="button"
                    className={styles.cancelBtn}
                    onClick={() => {
                      setShowForm(false);
                      setForm(EMPTY_FORM);
                      setFormError(null);
                    }}
                  >
                    İptal
                  </button>
                </div>

                {formError && (
                  <div className={styles.formError}>{formError}</div>
                )}
              </form>
            </div>
          </section>
        )}

        {/* Rules list */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>
              Tanımlı Kurallar{rules.length > 0 ? ` (${rules.length})` : ''}
            </h2>
          </div>

          {loading ? (
            <div className={styles.stateBox}>
              <span className={styles.muted}>Kurallar yükleniyor...</span>
            </div>
          ) : error ? (
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchRules}>
                Tekrar Dene
              </button>
            </div>
          ) : rules.length === 0 ? (
            <EmptyState
              icon={
                <svg
                  width="48"
                  height="48"
                  viewBox="0 0 48 48"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  aria-hidden="true"
                >
                  <rect x="6" y="10" width="36" height="28" rx="4" stroke="currentColor" strokeWidth="2" fill="none" />
                  <path d="M6 18h36" stroke="currentColor" strokeWidth="2" />
                  <path d="M16 28h8M16 33h5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  <circle cx="36" cy="30" r="6" stroke="currentColor" strokeWidth="2" fill="none" />
                  <path d="M36 27v3l2 2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
              title="Henüz otomasyon kuralı yok"
              subtitle="Metrik koşullarına göre otomatik uyarılar ve öneriler tanımlayın. İlk kuralınızı oluşturun."
              action={{
                label: 'Yeni Kural',
                onClick: () => {
                  setShowForm(true);
                  setFormError(null);
                  setForm(EMPTY_FORM);
                },
              }}
            />
          ) : (
            <div className={styles.rulesList}>
              {rules.map((rule) => {
                const ui = ruleUI[rule.id] ?? emptyUIState();
                const isBusy = busy[rule.id] ?? false;

                const summary = buildRuleSentence(
                  rule.scope,
                  rule.scope_filter ?? '',
                  rule.metric,
                  rule.comparator,
                  rule.threshold !== null ? String(rule.threshold) : '',
                  rule.window_days,
                  rule.action,
                );

                return (
                  <div key={rule.id} className={styles.ruleRow}>
                    {/* Main row */}
                    <div className={styles.ruleMain}>
                      <div className={styles.ruleContent}>
                        <div className={styles.ruleName}>{rule.name}</div>
                        <div className={styles.ruleSummary}>{summary}</div>
                        {rule.last_triggered_at && (
                          <div className={styles.ruleLastRun}>
                            Son tetiklenme:{' '}
                            {fmtDateTime(rule.last_triggered_at)}
                          </div>
                        )}
                        {/* Run result inline */}
                        {ui.runResult && (
                          <div style={{ marginTop: '0.375rem' }}>
                            <span
                              className={`${styles.runResult} ${
                                ui.runResult.triggered
                                  ? styles.runResultTriggered
                                  : styles.runResultNotTriggered
                              }`}
                            >
                              {ui.runResult.triggered
                                ? 'Tetiklendi'
                                : 'Tetiklenmedi'}
                            </span>
                            {ui.runResult.detail && (
                              <div className={styles.runDetail}>
                                {fmtRunDetail(ui.runResult.detail)}
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      <div className={styles.ruleActions}>
                        {/* Active toggle */}
                        <button
                          className={`${styles.ruleToggle} ${
                            rule.is_active
                              ? styles.ruleToggleActive
                              : styles.ruleToggleInactive
                          }`}
                          onClick={() => handleToggle(rule)}
                          disabled={isBusy}
                          title={
                            rule.is_active
                              ? 'Pasife al'
                              : 'Aktife al'
                          }
                        >
                          {rule.is_active ? 'Aktif' : 'Pasif'}
                        </button>

                        {/* Run now */}
                        <button
                          className={`${styles.actionBtn} ${ui.runLoading ? styles.actionBtnActive : ''}`}
                          onClick={() => handleRun(rule.id)}
                          disabled={ui.runLoading || isBusy}
                        >
                          {ui.runLoading ? 'Çalışıyor...' : 'Şimdi Çalıştır'}
                        </button>

                        {/* History toggle */}
                        <button
                          className={`${styles.actionBtn} ${ui.runsOpen ? styles.actionBtnActive : ''}`}
                          onClick={() => handleToggleRuns(rule.id)}
                          disabled={isBusy}
                        >
                          Geçmiş
                        </button>

                        {/* Delete */}
                        <button
                          className={`${styles.actionBtn} ${styles.actionBtnDanger}`}
                          onClick={() => handleDelete(rule.id)}
                          disabled={isBusy}
                        >
                          Sil
                        </button>
                      </div>
                    </div>

                    {/* Runs history panel */}
                    {ui.runsOpen && (
                      <div className={styles.runsPanel}>
                        <div className={styles.runsPanelTitle}>
                          Çalıştırma Geçmişi
                        </div>
                        {ui.runsLoading ? (
                          <div className={styles.runsEmpty}>
                            Yükleniyor...
                          </div>
                        ) : ui.runsError ? (
                          <div className={styles.runsEmpty}>
                            <span style={{ color: 'var(--color-danger)' }}>
                              {ui.runsError}
                            </span>
                          </div>
                        ) : ui.runs.length === 0 ? (
                          <div className={styles.runsEmpty}>
                            Henüz çalıştırma kaydı yok.
                          </div>
                        ) : (
                          <table className={styles.runsTable}>
                            <thead>
                              <tr>
                                <th>Tarih</th>
                                <th>Sonuç</th>
                                <th>Detay</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ui.runs.map((run, idx) => (
                                <tr key={idx}>
                                  <td style={{ whiteSpace: 'nowrap' }}>
                                    {fmtDateTime(run.ran_at)}
                                  </td>
                                  <td>
                                    <span
                                      className={`${styles.runResult} ${
                                        run.triggered
                                          ? styles.runResultTriggered
                                          : styles.runResultNotTriggered
                                      }`}
                                    >
                                      {run.triggered
                                        ? 'Tetiklendi'
                                        : 'Tetiklenmedi'}
                                    </span>
                                  </td>
                                  <td>{fmtRunDetail(run.detail)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <SuggestionsStrip
          title="Örnek otomasyonlar"
          suggestions={[
            { label: 'ROAS < 2x olunca uyar', href: '/automation' },
            { label: 'Bütçe aşımı alertı', href: '/automation' },
            { label: 'Dönüşüm düşüşü tespit', href: '/automation' },
          ]}
        />
      </main>
    </div>
  );
}
