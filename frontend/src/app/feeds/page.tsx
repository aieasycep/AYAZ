'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getFeedSources,
  createFeedSource,
  syncFeedSource,
  getFeedChannels,
  createFeedChannel,
  getChannelRules,
  createChannelRule,
  patchChannelRule,
  deleteChannelRule,
  getRulesImpact,
  simulateRule,
  lintChannelRules,
  ruleFromText,
  getChannelQuality,
  getPublicFeedUrl,
  enrichSource,
  applyEnrichment,
  type FeedSource,
  type FeedChannel,
  type FeedRule,
  type SourceType,
  type ChannelType,
  type OutputFormat,
  type RuleType,
  type RulesImpactResponse,
  type SimulateRuleResponse,
  type LintIssue,
  type RuleFromTextResponse,
  type FeedQualityResponse,
  type QualityIssue,
  type EnrichableField,
  type EnrichmentSuggestion,
} from '@/lib/feeds-api';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import EmptyState from '@/components/EmptyState';
import { parseApiError } from '@/lib/parseApiError';
import styles from './feeds.module.css';

// --- Label maps ---

const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  url_xml: 'URL (XML)',
  url_csv: 'URL (CSV)',
  upload: 'Dosya Yükleme',
};

const CHANNEL_TYPE_LABELS: Record<ChannelType, string> = {
  google_shopping: 'Google Shopping',
  meta_catalog: 'Meta Katalog',
  tiktok: 'TikTok',
  custom: 'Özel',
};

const RULE_TYPE_LABELS: Record<RuleType, string> = {
  set_value: 'Değer Ata',
  rename_field: 'Alan Yeniden Adlandır',
  find_replace: 'Bul & Değiştir',
  filter_include: 'Filtrele (Dahil Et)',
  filter_exclude: 'Filtrele (Hariç Tut)',
  calculated: 'Hesaplanmış Değer',
};

const OUTPUT_FORMAT_OPTIONS: { value: OutputFormat; label: string }[] = [
  { value: 'xml', label: 'XML' },
  { value: 'csv', label: 'CSV' },
  { value: 'json', label: 'JSON' },
  { value: 'tsv', label: 'TSV' },
];

// Linter code → Turkish friendly text
const LINT_CODE_LABELS: Record<string, string> = {
  no_effect: 'Bu kural hiçbir ürünü etkilemiyor',
  excludes_all: 'Bu kural neredeyse tüm ürünleri eliyor',
  shadowed: 'Daha önceki bir kural bunu gölgeliyor',
  duplicate: 'Yinelenen kural',
};

function fmtDate(iso: string | null): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Az önce';
  if (mins < 60) return `${mins} dk önce`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} sa önce`;
  const days = Math.floor(hrs / 24);
  return `${days} gün önce`;
}

function fmtRuleConfigSummary(type: RuleType, config: Record<string, unknown>): string {
  switch (type) {
    case 'set_value':
      return `${config.field ?? ''} = "${config.value ?? ''}"`;
    case 'rename_field':
      return `${config.from_field ?? config.from ?? ''} → ${config.to_field ?? config.to ?? ''}`;
    case 'find_replace':
      return `"${config.pattern ?? config.find ?? ''}" → "${config.replacement ?? config.replace ?? ''}" (${config.field ?? 'tüm alanlar'})`;
    case 'filter_include':
      return `${config.condition_field ?? config.field ?? ''} ${config.condition_op ?? config.operator ?? '='} "${config.condition_value ?? config.value ?? ''}"`;
    case 'filter_exclude':
      return `${config.condition_field ?? config.field ?? ''} ${config.condition_op ?? config.operator ?? '='} "${config.condition_value ?? config.value ?? ''}" (hariç)`;
    case 'calculated':
      return `${config.field ?? ''} = ${config.expression ?? ''}`;
    default:
      return JSON.stringify(config);
  }
}

// --- Rule config fields per type ---

interface RuleConfigState {
  // set_value
  sv_field: string;
  sv_value: string;
  // rename_field
  rf_from: string;
  rf_to: string;
  // find_replace
  fr_field: string;
  fr_pattern: string;
  fr_replacement: string;
  fr_use_regex: boolean;
  // filter_include / filter_exclude
  fi_condition_field: string;
  fi_condition_op: string;
  fi_condition_value: string;
  // calculated
  calc_field: string;
  calc_expression: string;
}

const DEFAULT_RULE_CONFIG: RuleConfigState = {
  sv_field: '', sv_value: '',
  rf_from: '', rf_to: '',
  fr_field: '', fr_pattern: '', fr_replacement: '', fr_use_regex: false,
  fi_condition_field: '', fi_condition_op: 'eq', fi_condition_value: '',
  calc_field: '', calc_expression: '',
};

function buildRuleConfig(type: RuleType, cfg: RuleConfigState): Record<string, unknown> {
  switch (type) {
    case 'set_value':
      return { field: cfg.sv_field, value: cfg.sv_value };
    case 'rename_field':
      return { from_field: cfg.rf_from, to_field: cfg.rf_to, drop_original: false };
    case 'find_replace':
      return {
        field: cfg.fr_field || undefined,
        pattern: cfg.fr_pattern,
        replacement: cfg.fr_replacement,
        use_regex: cfg.fr_use_regex,
      };
    case 'filter_include':
      return { condition_field: cfg.fi_condition_field, condition_op: cfg.fi_condition_op, condition_value: cfg.fi_condition_value };
    case 'filter_exclude':
      return { condition_field: cfg.fi_condition_field, condition_op: cfg.fi_condition_op, condition_value: cfg.fi_condition_value };
    case 'calculated':
      return { field: cfg.calc_field, expression: cfg.calc_expression };
  }
}

// Reverse of buildRuleConfig: map backend config keys → RuleConfigState
function configToFormState(type: RuleType, config: Record<string, unknown>): Partial<RuleConfigState> {
  switch (type) {
    case 'set_value':
      return {
        sv_field: String(config.field ?? ''),
        sv_value: String(config.value ?? ''),
      };
    case 'rename_field':
      return {
        rf_from: String(config.from_field ?? config.from ?? ''),
        rf_to: String(config.to_field ?? config.to ?? ''),
      };
    case 'find_replace':
      return {
        fr_field: String(config.field ?? ''),
        fr_pattern: String(config.pattern ?? config.find ?? ''),
        fr_replacement: String(config.replacement ?? config.replace ?? ''),
        fr_use_regex: Boolean(config.use_regex ?? false),
      };
    case 'filter_include':
    case 'filter_exclude':
      return {
        fi_condition_field: String(config.condition_field ?? config.field ?? ''),
        fi_condition_op: String(config.condition_op ?? config.operator ?? 'eq'),
        fi_condition_value: String(config.condition_value ?? config.value ?? ''),
      };
    case 'calculated':
      return {
        calc_field: String(config.field ?? ''),
        calc_expression: String(config.expression ?? ''),
      };
    default:
      return {};
  }
}

// --- CopyButton ---

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const el = document.createElement('textarea');
      el.value = text;
      el.style.position = 'fixed';
      el.style.opacity = '0';
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <button
      className={`${styles.copyBtn} ${copied ? styles.copyBtnCopied : ''}`}
      onClick={handleCopy}
      title="Feed URL'sini kopyala"
    >
      {copied ? 'Kopyalandı!' : 'Kopyala'}
    </button>
  );
}

// --- Lint chip ---

function LintChip({ issue }: { issue: LintIssue }) {
  const label = LINT_CODE_LABELS[issue.code] ?? issue.message;
  const chipClass =
    issue.severity === 'error'
      ? styles.lintChipError
      : issue.severity === 'warning'
      ? styles.lintChipWarn
      : styles.lintChipInfo;
  return <span className={`${styles.lintChip} ${chipClass}`} title={issue.message}>{label}</span>;
}

// --- Sample diff row ---

function SampleDiff({
  before,
  after,
}: {
  before: Record<string, unknown>[];
  after: Record<string, unknown>[];
}) {
  if (!before.length && !after.length) return null;
  const rows = Math.max(before.length, after.length);
  return (
    <div className={styles.sampleDiff}>
      {Array.from({ length: rows }).map((_, i) => {
        const b = before[i];
        const a = after[i];
        // Show the first key that differs
        const keys = b ? Object.keys(b) : a ? Object.keys(a) : [];
        const changedKey = keys.find((k) => b && a && String(b[k]) !== String(a[k])) ?? keys[0];
        if (!changedKey) return null;
        return (
          <div key={i} className={styles.sampleDiffRow}>
            <span className={styles.sampleDiffKey}>{changedKey}:</span>
            {b && (
              <span className={styles.sampleDiffBefore} title="Önce">
                {String(b[changedKey] ?? '')}
              </span>
            )}
            <span className={styles.sampleDiffArrow}>→</span>
            {a && (
              <span className={styles.sampleDiffAfter} title="Sonra">
                {String(a[changedKey] ?? '')}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// --- Quality score rating helper ---

function qualityRating(score: number): { label: string; mod: 'good' | 'mid' | 'bad' } {
  if (score >= 90) return { label: 'iyi', mod: 'good' };
  if (score >= 70) return { label: 'orta', mod: 'mid' };
  return { label: 'zayıf', mod: 'bad' };
}

// --- Quality issue row ---

function QualityIssueRow({ issue }: { issue: QualityIssue }) {
  const chipClass =
    issue.severity === 'error' ? styles.lintChipError : styles.lintChipWarn;
  return (
    <div className={styles.qualityIssueRow}>
      <span className={`${styles.lintChip} ${chipClass}`}>
        {issue.severity === 'error' ? 'hata' : 'uyarı'}
      </span>
      <div className={styles.qualityIssueMain}>
        <span className={styles.qualityIssueMsg}>{issue.message}</span>
        <span className={styles.qualityIssueMeta}>
          <span className={styles.qualityIssueField}>{issue.field}</span>
          <span className={styles.muted}>&middot; {issue.affected_count.toLocaleString('tr-TR')} ürün</span>
        </span>
      </div>
    </div>
  );
}

// --- Enrichment field labels ---

const ENRICH_FIELD_LABELS: Record<EnrichableField, string> = {
  color: 'Renk',
  brand: 'Marka',
  category: 'Kategori',
  material: 'Materyal',
  title: 'Başlık',
};

const ALL_ENRICH_FIELDS: EnrichableField[] = ['color', 'brand', 'category', 'material', 'title'];

// --- Toast notification ---

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 4000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  return (
    <div className={styles.toast} role="status" aria-live="polite">
      <span>{message}</span>
      <button className={styles.toastClose} onClick={onDismiss} aria-label="Kapat">×</button>
    </div>
  );
}

// --- Enrichment panel ---

function EnrichmentPanel({ source, onClose }: { source: FeedSource; onClose: () => void }) {
  const [selectedFields, setSelectedFields] = useState<EnrichableField[]>([...ALL_ENRICH_FIELDS]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [suggestions, setSuggestions] = useState<EnrichmentSuggestion[] | null>(null);
  const [sampled, setSampled] = useState(false);
  const [sampledTotal, setSampledTotal] = useState<number | null>(null);

  // approval state: key = `${product_id}::${field}`
  const [approvals, setApprovals] = useState<Record<string, boolean>>({});

  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function suggestionKey(s: EnrichmentSuggestion): string {
    return `${s.product_id}::${s.field}`;
  }

  function toggleField(f: EnrichableField) {
    setSelectedFields((prev) =>
      prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]
    );
  }

  async function handleFetchSuggestions() {
    if (selectedFields.length === 0) return;
    setLoading(true);
    setError(null);
    setSuggestions(null);
    setApprovals({});
    setApplyError(null);
    try {
      const res = await enrichSource(source.id, { fields: selectedFields });
      setSuggestions(res.suggestions);
      setSampled(res.sampled);
      setSampledTotal(res.sampled_total);
      // Pre-check high-confidence rows
      const initial: Record<string, boolean> = {};
      for (const s of res.suggestions) {
        initial[suggestionKey(s)] = s.confidence === 'high';
      }
      setApprovals(initial);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleApply() {
    if (!suggestions) return;
    setApplyError(null);
    setApplying(true);
    try {
      const checkedApprovals = suggestions
        .filter((s) => approvals[suggestionKey(s)])
        .map((s) => ({ product_id: s.product_id, field: s.field, value: s.suggested }));
      const res = await applyEnrichment(source.id, { approvals: checkedApprovals });
      setToast(`${res.applied_count} alan güncellendi`);
      setSuggestions(null);
      setApprovals({});
    } catch (err: unknown) {
      setApplyError(parseApiError(err));
    } finally {
      setApplying(false);
    }
  }

  const checkedCount = Object.values(approvals).filter(Boolean).length;

  function toggleApproval(key: string) {
    setApprovals((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  function shortProductId(id: string): string {
    return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id;
  }

  return (
    <div className={styles.enrichPanel}>
      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}

      <div className={styles.enrichHeader}>
        <span className={styles.enrichTitle}>AI ile Zenginleştir</span>
        <button className={styles.enrichCloseBtn} onClick={onClose} aria-label="Kapat">×</button>
      </div>

      {/* Field multiselect */}
      <div className={styles.enrichFieldRow}>
        {ALL_ENRICH_FIELDS.map((f) => (
          <label key={f} className={`${styles.enrichFieldChip} ${selectedFields.includes(f) ? styles.enrichFieldChipActive : ''}`}>
            <input
              type="checkbox"
              checked={selectedFields.includes(f)}
              onChange={() => toggleField(f)}
              className={styles.enrichFieldCheckbox}
            />
            {ENRICH_FIELD_LABELS[f]}
          </label>
        ))}
      </div>

      <div className={styles.enrichActions}>
        <button
          className={styles.primaryBtn}
          onClick={handleFetchSuggestions}
          disabled={loading || selectedFields.length === 0}
        >
          {loading ? 'Öneriler getiriliyor...' : 'Öneri Getir'}
        </button>
        {error && <span className={styles.formError}>{error}</span>}
      </div>

      {/* Review table */}
      {suggestions !== null && (
        <>
          {sampled && (
            <div className={styles.enrichSampledNote}>
              Sonuçlar ilk {sampledTotal != null ? sampledTotal.toLocaleString('tr-TR') : '...'} ürün üzerinden örneklenmiştir.
            </div>
          )}

          {suggestions.length === 0 ? (
            <div className={styles.enrichEmpty}>
              Zenginleştirilecek eksik alan bulunamadı
            </div>
          ) : (
            <>
              <div className={styles.enrichTable} role="table" aria-label="Zenginleştirme önerileri">
                <div className={styles.enrichTableHead} role="row">
                  <span role="columnheader" className={styles.enrichColCheck} />
                  <span role="columnheader" className={styles.enrichColProduct}>Ürün ID</span>
                  <span role="columnheader" className={styles.enrichColField}>Alan</span>
                  <span role="columnheader" className={styles.enrichColCurrent}>Mevcut</span>
                  <span role="columnheader" className={styles.enrichColArrow} />
                  <span role="columnheader" className={styles.enrichColSuggested}>Öneri</span>
                  <span role="columnheader" className={styles.enrichColConf}>Güven</span>
                </div>

                {suggestions.map((s) => {
                  const key = suggestionKey(s);
                  const isHigh = s.confidence === 'high';
                  return (
                    <div
                      key={key}
                      className={`${styles.enrichTableRow} ${approvals[key] ? styles.enrichTableRowChecked : ''}`}
                      role="row"
                    >
                      <span role="cell" className={styles.enrichColCheck}>
                        <input
                          type="checkbox"
                          checked={!!approvals[key]}
                          onChange={() => toggleApproval(key)}
                          aria-label={`${shortProductId(s.product_id)} — ${ENRICH_FIELD_LABELS[s.field]} onayla`}
                        />
                      </span>
                      <span role="cell" className={`${styles.enrichColProduct} ${styles.enrichProductId}`} title={s.product_id}>
                        {shortProductId(s.product_id)}
                      </span>
                      <span role="cell" className={styles.enrichColField}>
                        <span className={styles.enrichFieldBadge}>{ENRICH_FIELD_LABELS[s.field]}</span>
                      </span>
                      <span role="cell" className={`${styles.enrichColCurrent} ${!s.current ? styles.enrichEmpty_ : ''}`}>
                        {s.current ?? '— boş'}
                      </span>
                      <span role="cell" className={styles.enrichColArrow}>→</span>
                      <span role="cell" className={styles.enrichColSuggested}>
                        {s.suggested}
                      </span>
                      <span role="cell" className={styles.enrichColConf}>
                        <span className={`${styles.enrichConfChip} ${isHigh ? styles.enrichConfHigh : styles.enrichConfLow}`}>
                          {isHigh ? 'yüksek' : 'düşük'}
                        </span>
                      </span>
                    </div>
                  );
                })}
              </div>

              {applyError && <span className={styles.formError}>{applyError}</span>}

              <div className={styles.enrichApplyRow}>
                <button
                  className={styles.primaryBtn}
                  onClick={handleApply}
                  disabled={applying || checkedCount === 0}
                >
                  {applying ? 'Uygulanıyor...' : `Onaylananları Uygula (${checkedCount})`}
                </button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

// --- Rule editor for a channel ---

function RuleEditor({ channel }: { channel: FeedChannel }) {
  const [rules, setRules] = useState<FeedRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [rulesError, setRulesError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [ruleType, setRuleType] = useState<RuleType>('set_value');
  const [rulePos, setRulePos] = useState('');
  const [ruleCfg, setRuleCfg] = useState<RuleConfigState>({ ...DEFAULT_RULE_CONFIG });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Feature 2: Impact bar
  const [impact, setImpact] = useState<RulesImpactResponse | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [impactError, setImpactError] = useState<string | null>(null);

  // Feature 3: Simulate-before-save
  const [simResult, setSimResult] = useState<SimulateRuleResponse | null>(null);
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);

  // Feature 4: Linter
  const [lintIssues, setLintIssues] = useState<LintIssue[]>([]);
  const [lintLoading, setLintLoading] = useState(false);

  // Feature 5: Feed Quality
  const [quality, setQuality] = useState<FeedQualityResponse | null>(null);
  const [qualityLoading, setQualityLoading] = useState(false);
  const [qualityError, setQualityError] = useState<string | null>(null);

  // NL rule generator
  const [nlText, setNlText] = useState('');
  const [nlLoading, setNlLoading] = useState(false);
  const [nlError, setNlError] = useState<string | null>(null);
  const [nlResult, setNlResult] = useState<RuleFromTextResponse | null>(null);

  // Delete confirm
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchRules = useCallback(async () => {
    setRulesLoading(true);
    setRulesError(null);
    try {
      const data = await getChannelRules(channel.id);
      setRules(data);
    } catch (err: unknown) {
      setRulesError(parseApiError(err));
    } finally {
      setRulesLoading(false);
    }
  }, [channel.id]);

  // Auto-lint after rules load
  const runLint = useCallback(async () => {
    setLintLoading(true);
    try {
      const res = await lintChannelRules(channel.id);
      setLintIssues(res.issues);
    } catch {
      // non-fatal
    } finally {
      setLintLoading(false);
    }
  }, [channel.id]);

  useEffect(() => {
    fetchRules().then(() => runLint());
  }, [fetchRules, runLint]);

  function updateCfg(key: keyof RuleConfigState, value: string | boolean) {
    setRuleCfg((prev) => ({ ...prev, [key]: value }));
  }

  // NL rule generation
  async function handleNlGenerate() {
    const trimmed = nlText.trim();
    if (!trimmed) return;
    setNlLoading(true);
    setNlError(null);
    setNlResult(null);
    try {
      const res = await ruleFromText(channel.id, trimmed);
      // Apply generated rule_type and config to form state
      setRuleType(res.rule_type);
      setRuleCfg({ ...DEFAULT_RULE_CONFIG, ...configToFormState(res.rule_type, res.config) });
      setSimResult(null);
      setSimError(null);
      setNlResult(res);
    } catch (err: unknown) {
      setNlError(parseApiError(err));
    } finally {
      setNlLoading(false);
    }
  }

  // Feature 1: Pause toggle
  async function handleTogglePause(rule: FeedRule) {
    const newPaused = !rule.is_paused;
    // Optimistic update
    setRules((prev) =>
      prev.map((r) => (r.id === rule.id ? { ...r, is_paused: newPaused } : r))
    );
    try {
      const updated = await patchChannelRule(rule.id, { is_paused: newPaused });
      setRules((prev) => prev.map((r) => (r.id === rule.id ? updated : r)));
    } catch (err) {
      // Revert on failure
      setRules((prev) =>
        prev.map((r) => (r.id === rule.id ? { ...r, is_paused: rule.is_paused } : r))
      );
      alert(parseApiError(err));
    }
  }

  // Feature 2: Fetch impact
  async function handleFetchImpact() {
    setImpactLoading(true);
    setImpactError(null);
    try {
      const res = await getRulesImpact(channel.id);
      setImpact(res);
    } catch (err: unknown) {
      setImpactError(parseApiError(err));
    } finally {
      setImpactLoading(false);
    }
  }

  // Feature 5: Fetch quality
  async function handleFetchQuality() {
    setQualityLoading(true);
    setQualityError(null);
    try {
      const res = await getChannelQuality(channel.id);
      setQuality(res);
    } catch (err: unknown) {
      setQualityError(parseApiError(err));
    } finally {
      setQualityLoading(false);
    }
  }

  // Feature 3: Simulate
  async function handleSimulate() {
    setSimLoading(true);
    setSimError(null);
    setSimResult(null);
    try {
      const config = buildRuleConfig(ruleType, ruleCfg);
      const position = rulePos ? parseInt(rulePos, 10) : undefined;
      const res = await simulateRule(channel.id, { rule_type: ruleType, config, position });
      setSimResult(res);
    } catch (err: unknown) {
      setSimError(parseApiError(err));
    } finally {
      setSimLoading(false);
    }
  }

  async function handleAddRule(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      const position = rulePos ? parseInt(rulePos, 10) : rules.length + 1;
      const config = buildRuleConfig(ruleType, ruleCfg);
      await createChannelRule(channel.id, { position, rule_type: ruleType, config });
      setRuleCfg({ ...DEFAULT_RULE_CONFIG });
      setRulePos('');
      setShowForm(false);
      setSimResult(null);
      setSimError(null);
      setNlText('');
      setNlResult(null);
      setNlError(null);
      await fetchRules();
      await runLint();
      setImpact(null); // stale — user should re-run
    } catch (err: unknown) {
      setFormError(parseApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDeleteRule(ruleId: string) {
    if (deletingId !== ruleId) {
      setDeletingId(ruleId);
      return; // first click = confirm
    }
    try {
      await deleteChannelRule(ruleId);
      setRules((prev) => prev.filter((r) => r.id !== ruleId));
      setDeletingId(null);
      setImpact(null);
      await runLint();
    } catch (err) {
      setDeletingId(null);
      alert(parseApiError(err));
    }
  }

  // Impact stat lookup by rule_id
  function impactStatFor(ruleId: string) {
    return impact?.rules.find((r) => r.rule_id === ruleId) ?? null;
  }

  // Lint issues for a rule
  function lintIssuesFor(ruleId: string) {
    return lintIssues.filter((i) => i.rule_id === ruleId);
  }

  const totalLintErrors = lintIssues.filter((i) => i.severity === 'error').length;
  const totalLintWarnings = lintIssues.filter((i) => i.severity === 'warning').length;

  const publicUrl = getPublicFeedUrl(channel.public_token);

  return (
    <div className={styles.rulePanel}>
      {/* Public feed URL */}
      <div className={styles.publicUrlRow}>
        <span className={styles.publicUrlLabel}>Feed URL</span>
        <span className={styles.publicUrl} title={publicUrl}>{publicUrl}</span>
        <CopyButton text={publicUrl} />
      </div>

      {/* Rules header — replaced by SectionCard in linted content below */}

      {rulesLoading ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>Kurallar yükleniyor...</span>
        </div>
      ) : rulesError ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.errorText}>{rulesError}</span>
        </div>
      ) : (
        <>
          {rules.length === 0 ? (
            <div className={styles.stateBoxSm}>
              <span className={styles.muted}>Henüz kural yok.</span>
            </div>
          ) : (
            <>
              {/* Feature 2: Impact bar */}
              <div className={styles.impactBar}>
                {impact && (
                  <div className={styles.impactTotal}>
                    <span className={styles.impactLabel}>Toplam:</span>
                    <span className={styles.impactBefore}>{impact.total_before.toLocaleString('tr-TR')} ürün</span>
                    <span className={styles.impactArrow}>→</span>
                    <span className={styles.impactAfter}>{impact.total_after.toLocaleString('tr-TR')} ürün</span>
                    {impact.sampled && (
                      <span className={styles.impactSampled}>
                        (ilk {impact.sampled_total?.toLocaleString('tr-TR') ?? '...'} üründe hesaplandı)
                      </span>
                    )}
                  </div>
                )}
                {impactError && <span className={styles.formError}>{impactError}</span>}
                <button
                  className={styles.secondaryBtn}
                  onClick={handleFetchImpact}
                  disabled={impactLoading}
                >
                  {impactLoading ? 'Hesaplanıyor...' : 'Etkiyi Hesapla'}
                </button>
              </div>

              {/* Feature 5: Quality section */}
              <SectionCard title="Feed Kalitesi">
              <div className={styles.qualityBar}>
                {quality && (() => {
                  const { label, mod } = qualityRating(quality.score);
                  return (
                    <div className={styles.qualityContent}>
                      <div className={styles.qualityScoreRow}>
                        <span className={`${styles.qualityScore} ${styles[`qualityScore_${mod}`]}`}>
                          {quality.score}
                        </span>
                        <div className={styles.qualityScoreInfo}>
                          <span className={`${styles.qualityRatingLabel} ${styles[`qualityRatingLabel_${mod}`]}`}>
                            {label}
                          </span>
                          <span className={styles.qualityValidCount}>
                            {quality.valid.toLocaleString('tr-TR')}/{quality.total.toLocaleString('tr-TR')} ürün geçerli
                          </span>
                          {quality.sampled && (
                            <span className={styles.qualitySampled}>Örneklem üzerinde hesaplandı</span>
                          )}
                        </div>
                      </div>
                      {quality.issues.length === 0 ? (
                        <div className={styles.qualityEmpty}>
                          Tüm ürünler kanal gereksinimlerini karşılıyor
                        </div>
                      ) : (
                        <div className={styles.qualityIssueList}>
                          {quality.issues.map((issue, idx) => (
                            <QualityIssueRow key={idx} issue={issue} />
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })()}
                {qualityError && <span className={styles.formError}>{qualityError}</span>}
                <button
                  className={styles.secondaryBtn}
                  onClick={handleFetchQuality}
                  disabled={qualityLoading}
                >
                  {qualityLoading ? 'Kontrol ediliyor...' : 'Kalite Kontrolü'}
                </button>
              </div>
              </SectionCard>

              <div className={styles.ruleList}>
                {rules
                  .slice()
                  .sort((a, b) => a.position - b.position)
                  .map((rule) => {
                    const stat = impactStatFor(rule.id);
                    const issues = lintIssuesFor(rule.id);
                    const isConfirmDelete = deletingId === rule.id;
                    return (
                      <div
                        key={rule.id}
                        className={`${styles.ruleRow} ${rule.is_paused ? styles.ruleRowPaused : ''}`}
                      >
                        <span className={styles.rulePos}>{rule.position}</span>

                        {/* Feature 1: Pause toggle */}
                        <button
                          className={`${styles.pauseBtn} ${rule.is_paused ? styles.pauseBtnActive : ''}`}
                          onClick={() => handleTogglePause(rule)}
                          title={rule.is_paused ? 'Devam Ettir' : 'Duraklat'}
                          aria-label={rule.is_paused ? 'Devam Ettir' : 'Duraklat'}
                        >
                          {rule.is_paused ? '▶' : '⏸'}
                        </button>

                        <div className={styles.ruleRowMain}>
                          <div className={styles.ruleRowTop}>
                            <span className={styles.ruleType}>
                              {RULE_TYPE_LABELS[rule.rule_type] ?? rule.rule_type}
                            </span>
                            {rule.is_paused && (
                              <span className={styles.pausedBadge}>Duraklatıldı</span>
                            )}
                            <span className={styles.ruleConfig}>
                              {fmtRuleConfigSummary(rule.rule_type, rule.config)}
                            </span>
                          </div>

                          {/* Feature 2: per-rule impact counts */}
                          {stat && !rule.is_paused && (
                            <div className={styles.ruleImpact}>
                              <span>{stat.affected_count.toLocaleString('tr-TR')} ürün değişti</span>
                              {stat.excluded_count > 0 && (
                                <span className={styles.ruleImpactExcluded}>
                                  · {stat.excluded_count.toLocaleString('tr-TR')} hariç
                                </span>
                              )}
                            </div>
                          )}

                          {/* Feature 4: lint chips per rule */}
                          {issues.length > 0 && (
                            <div className={styles.lintChips}>
                              {issues.map((issue, idx) => (
                                <LintChip key={idx} issue={issue} />
                              ))}
                            </div>
                          )}
                        </div>

                        <button
                          className={`${styles.deleteRuleBtn} ${isConfirmDelete ? styles.deleteRuleBtnConfirm : ''}`}
                          onClick={() => handleDeleteRule(rule.id)}
                          title={isConfirmDelete ? 'Silmek için tekrar tıkla' : 'Kuralı Sil'}
                          aria-label={isConfirmDelete ? 'Silmek için tekrar tıkla' : 'Kuralı Sil'}
                          onBlur={() => { if (deletingId === rule.id) setDeletingId(null); }}
                        >
                          {isConfirmDelete ? '?' : '×'}
                        </button>
                      </div>
                    );
                  })}
              </div>
            </>
          )}

          {!showForm ? (
            <button
              className={styles.secondaryBtn}
              onClick={() => setShowForm(true)}
            >
              + Kural Ekle
            </button>
          ) : (
            <form className={styles.ruleForm} onSubmit={handleAddRule}>
              <div className={styles.ruleFormTitle}>Yeni Kural</div>

              {/* NL rule generator */}
              <div className={styles.nlRow}>
                <input
                  className={styles.input}
                  type="text"
                  placeholder='Örn: "stokta olmayan ürünleri çıkar" veya "başlığa marka ekle"'
                  value={nlText}
                  onChange={(e) => setNlText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      handleNlGenerate();
                    }
                  }}
                  disabled={nlLoading}
                  aria-label="Doğal dilde kural tanımı"
                />
                <button
                  type="button"
                  className={styles.primaryBtn}
                  onClick={handleNlGenerate}
                  disabled={nlLoading || !nlText.trim()}
                >
                  {nlLoading ? 'Üretiliyor...' : 'Kural Üret'}
                </button>
              </div>

              {nlError && (
                <span className={styles.formError}>{nlError}</span>
              )}

              {nlResult && (
                <div className={`${styles.nlNote} ${nlResult.confidence === 'low' ? styles.nlNoteWarn : styles.nlNoteInfo}`}>
                  {nlResult.confidence === 'low' && (
                    <div className={styles.nlWarnMsg}>
                      Emin değilim — lütfen üretilen kuralı kontrol edin
                    </div>
                  )}
                  <div className={styles.nlExplanation}>{nlResult.explanation}</div>
                  {nlResult.impact && (
                    <div className={styles.nlImpact}>
                      ~{nlResult.impact.affected_count.toLocaleString('tr-TR')} ürünü etkiler
                      {nlResult.impact.excluded_count > 0 && (
                        <>, {nlResult.impact.excluded_count.toLocaleString('tr-TR')} hariç</>
                      )}
                    </div>
                  )}
                </div>
              )}

              <div className={styles.formRow}>
                <div className={styles.field}>
                  <label className={styles.label}>Kural Türü</label>
                  <select
                    className={styles.select}
                    value={ruleType}
                    onChange={(e) => {
                      setRuleType(e.target.value as RuleType);
                      setRuleCfg({ ...DEFAULT_RULE_CONFIG });
                      setSimResult(null);
                      setSimError(null);
                    }}
                  >
                    {(Object.entries(RULE_TYPE_LABELS) as [RuleType, string][]).map(([v, l]) => (
                      <option key={v} value={v}>{l}</option>
                    ))}
                  </select>
                </div>
                <div className={styles.field} style={{ maxWidth: '80px' }}>
                  <label className={styles.label}>Pozisyon</label>
                  <input
                    className={styles.input}
                    type="number"
                    min="1"
                    placeholder={String(rules.length + 1)}
                    value={rulePos}
                    onChange={(e) => setRulePos(e.target.value)}
                  />
                </div>
              </div>

              {/* Config fields by type */}
              {ruleType === 'set_value' && (
                <div className={styles.formRow}>
                  <div className={styles.field}>
                    <label className={styles.label}>Alan</label>
                    <input className={styles.input} placeholder="title" value={ruleCfg.sv_field} onChange={(e) => updateCfg('sv_field', e.target.value)} required />
                  </div>
                  <div className={styles.field}>
                    <label className={styles.label}>Değer</label>
                    <input className={styles.input} placeholder="Sabit değer" value={ruleCfg.sv_value} onChange={(e) => updateCfg('sv_value', e.target.value)} required />
                  </div>
                </div>
              )}

              {ruleType === 'rename_field' && (
                <div className={styles.formRow}>
                  <div className={styles.field}>
                    <label className={styles.label}>Eski Ad</label>
                    <input className={styles.input} placeholder="g:id" value={ruleCfg.rf_from} onChange={(e) => updateCfg('rf_from', e.target.value)} required />
                  </div>
                  <div className={styles.field}>
                    <label className={styles.label}>Yeni Ad</label>
                    <input className={styles.input} placeholder="id" value={ruleCfg.rf_to} onChange={(e) => updateCfg('rf_to', e.target.value)} required />
                  </div>
                </div>
              )}

              {ruleType === 'find_replace' && (
                <div className={styles.formRow}>
                  <div className={styles.field}>
                    <label className={styles.label}>Alan (opsiyonel)</label>
                    <input className={styles.input} placeholder="description" value={ruleCfg.fr_field} onChange={(e) => updateCfg('fr_field', e.target.value)} />
                  </div>
                  <div className={styles.field}>
                    <label className={styles.label}>Ara</label>
                    <input className={styles.input} placeholder="Aranacak metin" value={ruleCfg.fr_pattern} onChange={(e) => updateCfg('fr_pattern', e.target.value)} required />
                  </div>
                  <div className={styles.field}>
                    <label className={styles.label}>Değiştir</label>
                    <input className={styles.input} placeholder="Yeni metin" value={ruleCfg.fr_replacement} onChange={(e) => updateCfg('fr_replacement', e.target.value)} />
                  </div>
                  <div className={styles.field} style={{ maxWidth: '100px' }}>
                    <label className={styles.label}>Regex</label>
                    <label className={styles.checkboxLabel}>
                      <input
                        type="checkbox"
                        checked={ruleCfg.fr_use_regex}
                        onChange={(e) => updateCfg('fr_use_regex', e.target.checked)}
                      />
                      Regex kullan
                    </label>
                  </div>
                </div>
              )}

              {(ruleType === 'filter_include' || ruleType === 'filter_exclude') && (
                <div className={styles.formRow}>
                  <div className={styles.field}>
                    <label className={styles.label}>Alan</label>
                    <input className={styles.input} placeholder="availability" value={ruleCfg.fi_condition_field} onChange={(e) => updateCfg('fi_condition_field', e.target.value)} required />
                  </div>
                  <div className={styles.field} style={{ maxWidth: '160px' }}>
                    <label className={styles.label}>Koşul</label>
                    <select className={styles.select} value={ruleCfg.fi_condition_op} onChange={(e) => updateCfg('fi_condition_op', e.target.value)}>
                      <option value="eq">Eşit (=)</option>
                      <option value="neq">Eşit değil (!=)</option>
                      <option value="contains">İçerir</option>
                      <option value="not_contains">İçermez</option>
                      <option value="gt">Büyük (&gt;)</option>
                      <option value="lt">Küçük (&lt;)</option>
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label className={styles.label}>Değer</label>
                    <input className={styles.input} placeholder="in stock" value={ruleCfg.fi_condition_value} onChange={(e) => updateCfg('fi_condition_value', e.target.value)} required />
                  </div>
                </div>
              )}

              {ruleType === 'calculated' && (
                <div className={styles.formRow}>
                  <div className={styles.field}>
                    <label className={styles.label}>Hedef Alan</label>
                    <input className={styles.input} placeholder="sale_price" value={ruleCfg.calc_field} onChange={(e) => updateCfg('calc_field', e.target.value)} required />
                  </div>
                  <div className={styles.field} style={{ flex: 2 }}>
                    <label className={styles.label}>İfade</label>
                    <input className={styles.input} placeholder="{price} * 0.9" value={ruleCfg.calc_expression} onChange={(e) => updateCfg('calc_expression', e.target.value)} required />
                  </div>
                </div>
              )}

              {/* Feature 3: Simulate preview */}
              <div className={styles.simulateRow}>
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  onClick={handleSimulate}
                  disabled={simLoading}
                >
                  {simLoading ? 'Önizleniyor...' : 'Önizle'}
                </button>
                {simError && <span className={styles.formError}>{simError}</span>}
              </div>

              {simResult && (
                <div className={styles.simResult}>
                  <div className={styles.simSummary}>
                    Bu kural ~<strong>{simResult.affected_count.toLocaleString('tr-TR')}</strong> ürünü etkiler
                    {simResult.excluded_count > 0 && (
                      <>, <strong>{simResult.excluded_count.toLocaleString('tr-TR')}</strong> ürünü hariç tutar</>
                    )}
                  </div>
                  <SampleDiff before={simResult.sample_before} after={simResult.sample_after} />
                </div>
              )}

              {formError && <span className={styles.formError}>{formError}</span>}

              <div className={styles.formRow}>
                <button type="submit" className={styles.primaryBtn} disabled={submitting}>
                  {submitting ? 'Ekleniyor...' : 'Kural Ekle'}
                </button>
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  onClick={() => {
                    setShowForm(false);
                    setFormError(null);
                    setSimResult(null);
                    setSimError(null);
                    setNlText('');
                    setNlResult(null);
                    setNlError(null);
                  }}
                  disabled={submitting}
                >
                  İptal
                </button>
              </div>
            </form>
          )}
        </>
      )}
    </div>
  );
}

// --- Channel panel for a selected source ---

function ChannelPanel({ source }: { source: FeedSource }) {
  const [channels, setChannels] = useState<FeedChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [expandedChannelId, setExpandedChannelId] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [chName, setChName] = useState('');
  const [chType, setChType] = useState<ChannelType>('google_shopping');
  const [chFormat, setChFormat] = useState<OutputFormat>('xml');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchChannels = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getFeedChannels(source.id);
      setChannels(data);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, [source.id]);

  useEffect(() => {
    fetchChannels();
    setExpandedChannelId(null);
  }, [fetchChannels]);

  async function handleAddChannel(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await createFeedChannel(source.id, {
        name: chName,
        channel_type: chType,
        output_format: chFormat,
      });
      setChName('');
      setShowForm(false);
      await fetchChannels();
    } catch (err: unknown) {
      setFormError(parseApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  function toggleChannel(id: string) {
    setExpandedChannelId((prev) => (prev === id ? null : id));
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>Kanallar — {source.name}</h2>
        {!showForm && (
          <button className={styles.secondaryBtn} onClick={() => setShowForm(true)}>
            + Kanal Ekle
          </button>
        )}
      </div>

      {showForm && (
        <form className={styles.formBox} onSubmit={handleAddChannel}>
          <div className={styles.formRow}>
            <div className={styles.field}>
              <label className={styles.label}>Kanal Adı</label>
              <input
                className={styles.input}
                placeholder="Google Shopping TR"
                value={chName}
                onChange={(e) => setChName(e.target.value)}
                required
                disabled={submitting}
              />
            </div>
            <div className={styles.field} style={{ maxWidth: '180px' }}>
              <label className={styles.label}>Platform</label>
              <select
                className={styles.select}
                value={chType}
                onChange={(e) => setChType(e.target.value as ChannelType)}
                disabled={submitting}
              >
                {(Object.entries(CHANNEL_TYPE_LABELS) as [ChannelType, string][]).map(([v, l]) => (
                  <option key={v} value={v}>{l}</option>
                ))}
              </select>
            </div>
            <div className={styles.field} style={{ maxWidth: '110px' }}>
              <label className={styles.label}>Format</label>
              <select
                className={styles.select}
                value={chFormat}
                onChange={(e) => setChFormat(e.target.value as OutputFormat)}
                disabled={submitting}
              >
                {OUTPUT_FORMAT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>
          {formError && <span className={styles.formError}>{formError}</span>}
          <div className={styles.formRow}>
            <button type="submit" className={styles.primaryBtn} disabled={submitting}>
              {submitting ? 'Oluşturuluyor...' : 'Kanal Oluştur'}
            </button>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={() => { setShowForm(false); setFormError(null); }}
              disabled={submitting}
            >
              İptal
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div className={styles.stateBox}>
          <span className={styles.muted}>Kanallar yükleniyor...</span>
        </div>
      ) : error ? (
        <div className={styles.stateBox}>
          <span className={styles.errorText}>{error}</span>
          <br />
          <button className={styles.secondaryBtn} style={{ marginTop: '0.75rem' }} onClick={fetchChannels}>
            Tekrar Dene
          </button>
        </div>
      ) : channels.length === 0 ? (
        <EmptyState
          title="Bu kaynağa bağlı kanal yok"
          subtitle="Yeni bir kanal ekleyerek ürünlerinizi kanallara göre özelleştirin"
          action={{ label: '+ Kanal Ekle', onClick: () => setShowForm(true) }}
        />
      ) : (
        <div className={styles.channelGrid}>
          {channels.map((ch) => {
            const expanded = expandedChannelId === ch.id;
            return (
              <div key={ch.id} className={styles.channelCard}>
                <div
                  className={styles.channelCardHeader}
                  onClick={() => toggleChannel(ch.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && toggleChannel(ch.id)}
                  aria-expanded={expanded}
                >
                  <span className={styles.channelName}>{ch.name}</span>
                  <span className={styles.channelTypeBadge}>
                    {CHANNEL_TYPE_LABELS[ch.channel_type] ?? ch.channel_type}
                  </span>
                  <span className={styles.muted} style={{ fontSize: '0.775rem' }}>
                    {ch.output_format.toUpperCase()}
                  </span>
                  <label className={styles.toggle} onClick={(e) => e.stopPropagation()} aria-label="Aktif/Pasif">
                    <input type="checkbox" defaultChecked={ch.is_active} readOnly />
                    <span className={styles.toggleSlider} />
                  </label>
                  <span className={styles.muted} style={{ fontSize: '0.8rem' }}>
                    {expanded ? '▲' : '▼'}
                  </span>
                </div>

                {expanded && <RuleEditor channel={ch} />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// --- Main feeds page ---

export default function FeedsPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  const [sources, setSources] = useState<FeedSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);

  // New source form
  const [showNewSource, setShowNewSource] = useState(false);
  const [nsName, setNsName] = useState('');
  const [nsType, setNsType] = useState<SourceType>('url_xml');
  const [nsUrl, setNsUrl] = useState('');
  const [nsSubmitting, setNsSubmitting] = useState(false);
  const [nsError, setNsError] = useState<string | null>(null);

  // Sync state per source
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});

  // Enrichment panel open/close
  const [enrichSourceId, setEnrichSourceId] = useState<string | null>(null);

  const fetchSources = useCallback(async () => {
    setSourcesLoading(true);
    setSourcesError(null);
    try {
      const data = await getFeedSources();
      setSources(data);
      if (data.length > 0 && !selectedSourceId) {
        setSelectedSourceId(data[0].id);
      }
    } catch (err: unknown) {
      setSourcesError(parseApiError(err));
    } finally {
      setSourcesLoading(false);
    }
  }, [selectedSourceId]);

  useEffect(() => {
    if (!getToken()) return;
    fetchSources();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreateSource(e: React.FormEvent) {
    e.preventDefault();
    setNsError(null);
    setNsSubmitting(true);
    try {
      const created = await createFeedSource({ name: nsName, source_type: nsType, source_url: nsUrl });
      setSources((prev) => [...prev, created]);
      setSelectedSourceId(created.id);
      setNsName('');
      setNsUrl('');
      setShowNewSource(false);
    } catch (err: unknown) {
      setNsError(parseApiError(err));
    } finally {
      setNsSubmitting(false);
    }
  }

  async function handleSync(source: FeedSource) {
    setSyncing((prev) => ({ ...prev, [source.id]: true }));
    try {
      const updated = await syncFeedSource(source.id);
      setSources((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
    } catch (err) {
      alert(parseApiError(err));
    } finally {
      setSyncing((prev) => ({ ...prev, [source.id]: false }));
    }
  }

  const selectedSource = sources.find((s) => s.id === selectedSourceId) ?? null;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        <div>
          <h1 className={styles.pageTitle}>Feed Yönetimi</h1>
          <p className={styles.pageSubtitle}>
            Ürün feedlerinizi yönetin, kanallara özel çıktılar oluşturun ve herkese açık feed URL&apos;leri paylaşın.
          </p>
        </div>

        <div className={styles.layout}>
          {/* Left: source list */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>Feed Kaynakları</h2>
              {!showNewSource && (
                <button className={styles.secondaryBtn} onClick={() => setShowNewSource(true)}>
                  + Yeni Feed
                </button>
              )}
            </div>

            {showNewSource && (
              <form className={styles.formBox} onSubmit={handleCreateSource}>
                <div className={styles.field}>
                  <label className={styles.label}>Feed Adı</label>
                  <input
                    className={styles.input}
                    placeholder="Ana Ürün Katalogu"
                    value={nsName}
                    onChange={(e) => setNsName(e.target.value)}
                    required
                    disabled={nsSubmitting}
                  />
                </div>
                <div className={styles.field}>
                  <label className={styles.label}>Kaynak Türü</label>
                  <select
                    className={styles.select}
                    value={nsType}
                    onChange={(e) => setNsType(e.target.value as SourceType)}
                    disabled={nsSubmitting}
                  >
                    {(Object.entries(SOURCE_TYPE_LABELS) as [SourceType, string][]).map(([v, l]) => (
                      <option key={v} value={v}>{l}</option>
                    ))}
                  </select>
                </div>
                {nsType !== 'upload' && (
                  <div className={styles.field}>
                    <label className={styles.label}>Kaynak URL</label>
                    <input
                      className={styles.input}
                      type="url"
                      placeholder="https://example.com/feed.xml"
                      value={nsUrl}
                      onChange={(e) => setNsUrl(e.target.value)}
                      required
                      disabled={nsSubmitting}
                    />
                  </div>
                )}
                {nsError && <span className={styles.formError}>{nsError}</span>}
                <div className={styles.formRow}>
                  <button type="submit" className={styles.primaryBtn} disabled={nsSubmitting}>
                    {nsSubmitting ? 'Oluşturuluyor...' : 'Oluştur'}
                  </button>
                  <button
                    type="button"
                    className={styles.secondaryBtn}
                    onClick={() => { setShowNewSource(false); setNsError(null); }}
                    disabled={nsSubmitting}
                  >
                    İptal
                  </button>
                </div>
              </form>
            )}

            {sourcesLoading ? (
              <div className={styles.stateBox}>
                <span className={styles.muted}>Yükleniyor...</span>
              </div>
            ) : sourcesError ? (
              <div className={styles.stateBox}>
                <span className={styles.errorText}>{sourcesError}</span>
                <br />
                <button className={styles.secondaryBtn} style={{ marginTop: '0.75rem' }} onClick={fetchSources}>
                  Tekrar Dene
                </button>
              </div>
            ) : sources.length === 0 ? (
              <EmptyState
                title="Henüz feed kaynağı yok"
                subtitle="İlk feed kaynağınızı ekleyerek başlayın"
                action={{ label: '+ Yeni Feed', onClick: () => setShowNewSource(true) }}
              />
            ) : (
              <div className={styles.sourceList}>
                {sources.map((src) => (
                  <div key={src.id}>
                    <div
                      className={`${styles.sourceItem} ${selectedSourceId === src.id ? styles.sourceItemActive : ''}`}
                      onClick={() => setSelectedSourceId(src.id)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => e.key === 'Enter' && setSelectedSourceId(src.id)}
                    >
                      <span className={`${styles.sourceDot} ${selectedSourceId === src.id ? styles.sourceDotActive : ''}`} />
                      <div className={styles.sourceInfo}>
                        <div className={styles.sourceName}>
                          {src.name}
                          {src.item_count != null && (
                            <span className={styles.itemCountBadge} style={{ marginLeft: '0.5rem' }}>
                              {src.item_count.toLocaleString('tr-TR')}
                            </span>
                          )}
                        </div>
                        <div className={styles.sourceMeta}>
                          {SOURCE_TYPE_LABELS[src.source_type]}
                          {src.last_synced
                            ? ` · ${fmtRelative(src.last_synced)}`
                            : ' · Hiç senkronize edilmedi'}
                        </div>
                      </div>
                      <button
                        className={styles.syncBtn}
                        onClick={(e) => { e.stopPropagation(); handleSync(src); }}
                        disabled={syncing[src.id] ?? false}
                        title="Senkronize Et"
                      >
                        {syncing[src.id] ? '...' : '↻ Sync'}
                      </button>
                    </div>
                    {selectedSourceId === src.id && (
                      <div className={styles.sourceEnrichRow}>
                        <button
                          className={styles.aiBtn}
                          onClick={(e) => {
                            e.stopPropagation();
                            setEnrichSourceId((prev) => (prev === src.id ? null : src.id));
                          }}
                          aria-expanded={enrichSourceId === src.id}
                        >
                          ✦ AI ile Zenginleştir
                        </button>
                      </div>
                    )}
                    {enrichSourceId === src.id && (
                      <EnrichmentPanel
                        source={src}
                        onClose={() => setEnrichSourceId(null)}
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right: channel panel */}
          <div>
            {selectedSource ? (
              <ChannelPanel source={selectedSource} />
            ) : (
              <div className={styles.card}>
                <div className={styles.stateBox}>
                  <span className={styles.muted}>
                    {sourcesLoading ? 'Yükleniyor...' : 'Sol taraftan bir feed kaynağı seçin.'}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
