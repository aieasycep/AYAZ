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
  getPublicFeedUrl,
  type FeedSource,
  type FeedChannel,
  type FeedRule,
  type SourceType,
  type ChannelType,
  type OutputFormat,
  type RuleType,
} from '@/lib/feeds-api';
import AppNav from '@/components/AppNav';
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
  custom: 'Ozel',
};

const RULE_TYPE_LABELS: Record<RuleType, string> = {
  set_value: 'Deger Ata',
  rename_field: 'Alan Yeniden Adlandir',
  find_replace: 'Bul & Degistir',
  filter_include: 'Filtrele (Dahil Et)',
  filter_exclude: 'Filtrele (Hariç Tut)',
  calculated: 'Hesaplanmis Deger',
};

const OUTPUT_FORMAT_OPTIONS: { value: OutputFormat; label: string }[] = [
  { value: 'xml', label: 'XML' },
  { value: 'csv', label: 'CSV' },
  { value: 'json', label: 'JSON' },
  { value: 'tsv', label: 'TSV' },
];

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

function fmtRuleConfigSummary(type: RuleType, config: Record<string, unknown>): string {
  switch (type) {
    case 'set_value':
      return `${config.field ?? ''} = "${config.value ?? ''}"`;
    case 'rename_field':
      return `${config.from ?? ''} -> ${config.to ?? ''}`;
    case 'find_replace':
      return `"${config.find ?? ''}" -> "${config.replace ?? ''}" (${config.field ?? 'tüm alanlar'})`;
    case 'filter_include':
      return `${config.field ?? ''} ${config.operator ?? '='} "${config.value ?? ''}"`;
    case 'filter_exclude':
      return `${config.field ?? ''} ${config.operator ?? '='} "${config.value ?? ''}" (hariç)`;
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
  fr_find: string;
  fr_replace: string;
  // filter_include / filter_exclude
  fi_field: string;
  fi_operator: string;
  fi_value: string;
  // calculated
  calc_field: string;
  calc_expression: string;
}

const DEFAULT_RULE_CONFIG: RuleConfigState = {
  sv_field: '', sv_value: '',
  rf_from: '', rf_to: '',
  fr_field: '', fr_find: '', fr_replace: '',
  fi_field: '', fi_operator: 'eq', fi_value: '',
  calc_field: '', calc_expression: '',
};

function buildRuleConfig(type: RuleType, cfg: RuleConfigState): Record<string, unknown> {
  switch (type) {
    case 'set_value':
      return { field: cfg.sv_field, value: cfg.sv_value };
    case 'rename_field':
      return { from: cfg.rf_from, to: cfg.rf_to };
    case 'find_replace':
      return { field: cfg.fr_field || undefined, find: cfg.fr_find, replace: cfg.fr_replace };
    case 'filter_include':
      return { field: cfg.fi_field, operator: cfg.fi_operator, value: cfg.fi_value };
    case 'filter_exclude':
      return { field: cfg.fi_field, operator: cfg.fi_operator, value: cfg.fi_value };
    case 'calculated':
      return { field: cfg.calc_field, expression: cfg.calc_expression };
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
      // Fallback for non-HTTPS or old browsers
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
      {copied ? 'Kopyalandi!' : 'Kopyala'}
    </button>
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

  const fetchRules = useCallback(async () => {
    setRulesLoading(true);
    setRulesError(null);
    try {
      const data = await getChannelRules(channel.id);
      setRules(data);
    } catch (err: unknown) {
      setRulesError(err instanceof Error ? err.message : 'Kurallar yüklenemedi');
    } finally {
      setRulesLoading(false);
    }
  }, [channel.id]);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  function updateCfg(key: keyof RuleConfigState, value: string) {
    setRuleCfg((prev) => ({ ...prev, [key]: value }));
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
      await fetchRules();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Kural eklenemedi');
    } finally {
      setSubmitting(false);
    }
  }

  const publicUrl = getPublicFeedUrl(channel.public_token);

  return (
    <div className={styles.rulePanel}>
      {/* Public feed URL */}
      <div className={styles.publicUrlRow}>
        <span className={styles.publicUrlLabel}>Feed URL</span>
        <span className={styles.publicUrl} title={publicUrl}>{publicUrl}</span>
        <CopyButton text={publicUrl} />
      </div>

      <div className={styles.rulePanelTitle}>Kurallar</div>

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
            <div className={styles.ruleList}>
              {rules
                .slice()
                .sort((a, b) => a.position - b.position)
                .map((rule) => (
                  <div key={rule.id} className={styles.ruleRow}>
                    <span className={styles.rulePos}>{rule.position}</span>
                    <span className={styles.ruleType}>
                      {RULE_TYPE_LABELS[rule.rule_type] ?? rule.rule_type}
                    </span>
                    <span className={styles.ruleConfig}>
                      {fmtRuleConfigSummary(rule.rule_type, rule.config)}
                    </span>
                  </div>
                ))}
            </div>
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

              <div className={styles.formRow}>
                <div className={styles.field}>
                  <label className={styles.label}>Kural Türü</label>
                  <select
                    className={styles.select}
                    value={ruleType}
                    onChange={(e) => {
                      setRuleType(e.target.value as RuleType);
                      setRuleCfg({ ...DEFAULT_RULE_CONFIG });
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
                    <label className={styles.label}>Deger</label>
                    <input className={styles.input} placeholder="Sabit deger" value={ruleCfg.sv_value} onChange={(e) => updateCfg('sv_value', e.target.value)} required />
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
                    <label className={styles.label}>Bul</label>
                    <input className={styles.input} placeholder="Aranacak metin" value={ruleCfg.fr_find} onChange={(e) => updateCfg('fr_find', e.target.value)} required />
                  </div>
                  <div className={styles.field}>
                    <label className={styles.label}>Degistir</label>
                    <input className={styles.input} placeholder="Yeni metin" value={ruleCfg.fr_replace} onChange={(e) => updateCfg('fr_replace', e.target.value)} />
                  </div>
                </div>
              )}

              {(ruleType === 'filter_include' || ruleType === 'filter_exclude') && (
                <div className={styles.formRow}>
                  <div className={styles.field}>
                    <label className={styles.label}>Alan</label>
                    <input className={styles.input} placeholder="price" value={ruleCfg.fi_field} onChange={(e) => updateCfg('fi_field', e.target.value)} required />
                  </div>
                  <div className={styles.field} style={{ maxWidth: '120px' }}>
                    <label className={styles.label}>Kosul</label>
                    <select className={styles.select} value={ruleCfg.fi_operator} onChange={(e) => updateCfg('fi_operator', e.target.value)}>
                      <option value="eq">Esit (=)</option>
                      <option value="neq">Esit degil (!=)</option>
                      <option value="gt">Büyük (&gt;)</option>
                      <option value="gte">Büyük eşit (&gt;=)</option>
                      <option value="lt">Küçük (&lt;)</option>
                      <option value="lte">Küçük eşit (&lt;=)</option>
                      <option value="contains">Içerir</option>
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label className={styles.label}>Deger</label>
                    <input className={styles.input} placeholder="0" value={ruleCfg.fi_value} onChange={(e) => updateCfg('fi_value', e.target.value)} required />
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
                    <label className={styles.label}>Ifade</label>
                    <input className={styles.input} placeholder="price * 0.9" value={ruleCfg.calc_expression} onChange={(e) => updateCfg('calc_expression', e.target.value)} required />
                  </div>
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
                  onClick={() => { setShowForm(false); setFormError(null); }}
                  disabled={submitting}
                >
                  Iptal
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
      setError(err instanceof Error ? err.message : 'Kanallar yüklenemedi');
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
      setFormError(err instanceof Error ? err.message : 'Kanal eklenemedi');
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
              <label className={styles.label}>Kanal Adi</label>
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
              Iptal
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
        <div className={styles.stateBox}>
          <span className={styles.muted}>Bu kaynaga bağli kanal yok. Yeni bir kanal ekleyin.</span>
        </div>
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
      setSourcesError(err instanceof Error ? err.message : 'Kaynaklar yüklenemedi');
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
      setNsError(err instanceof Error ? err.message : 'Kaynak oluşturulamadı');
    } finally {
      setNsSubmitting(false);
    }
  }

  async function handleSync(source: FeedSource) {
    setSyncing((prev) => ({ ...prev, [source.id]: true }));
    try {
      const updated = await syncFeedSource(source.id);
      setSources((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
    } catch {
      // non-fatal — user can retry
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
            Ürün feedlerinizi yönetin, kanallara özel çiktilar oluşturun ve herkese açık feed URL'leri paylaşin.
          </p>
        </div>

        <div className={styles.layout}>
          {/* Left: source list */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>Feed Kaynaklari</h2>
              {!showNewSource && (
                <button className={styles.secondaryBtn} onClick={() => setShowNewSource(true)}>
                  + Yeni Feed
                </button>
              )}
            </div>

            {showNewSource && (
              <form className={styles.formBox} onSubmit={handleCreateSource}>
                <div className={styles.field}>
                  <label className={styles.label}>Feed Adi</label>
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
                    Iptal
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
              <div className={styles.stateBox}>
                <span className={styles.muted}>Henüz bir feed kaynagi yok.</span>
              </div>
            ) : (
              <div className={styles.sourceList}>
                {sources.map((src) => (
                  <div
                    key={src.id}
                    className={`${styles.sourceItem} ${selectedSourceId === src.id ? styles.sourceItemActive : ''}`}
                    onClick={() => setSelectedSourceId(src.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && setSelectedSourceId(src.id)}
                  >
                    <span className={`${styles.sourceDot} ${selectedSourceId === src.id ? styles.sourceDotActive : ''}`} />
                    <div className={styles.sourceInfo}>
                      <div className={styles.sourceName}>{src.name}</div>
                      <div className={styles.sourceMeta}>
                        {SOURCE_TYPE_LABELS[src.source_type]}
                        {src.item_count != null ? ` · ${src.item_count.toLocaleString('tr-TR')} ürün` : ''}
                        {src.last_synced ? ` · ${fmtDate(src.last_synced)}` : ''}
                      </div>
                    </div>
                    <button
                      className={styles.syncBtn}
                      onClick={(e) => { e.stopPropagation(); handleSync(src); }}
                      disabled={syncing[src.id] ?? false}
                      title="Senkronize Et"
                    >
                      {syncing[src.id] ? '...' : 'Sync'}
                    </button>
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
                    {sourcesLoading ? 'Yükleniyor...' : 'Sol taraftan bir feed kaynagi seçin.'}
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
