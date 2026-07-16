'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { getToken } from '@/lib/api';
import {
  getTrackingSources,
  createTrackingSource,
  getSourceSnippet,
  getSourceEvents,
  retryEvent,
  getSourceDestinations,
  getSourceStats,
  createDestination,
  deleteDestination,
  patchTrackingSource,
  patchDestination,
  getCollectUrl,
  toggleEventConfig,
  CONSENT_SIGNAL_LABELS,
  ALL_CONSENT_SIGNALS,
  PLATFORM_DEFAULT_CONSENT,
  MATCH_FIELD_LABELS,
  MATCH_TIER_LABELS,
  MATCH_TIER_ORDER,
  type MatchQualityStats,
  type TrackingSource,
  type TrackingDestination,
  type TrackingEvent,
  type TrackingStats,
  type EventStat,
  type DestinationPlatform,
  type EventStatus,
  type SnippetInfo,
  type ConsentSignal,
} from '@/lib/tracking-api';
import DateRangePresets, {
  computePreset,
  detectPreset,
  type PresetKey,
} from '@/components/DateRangePresets';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import EmptyState from '@/components/EmptyState';
import { parseApiError } from '@/lib/parseApiError';
import { downloadRowsAsCsv } from '@/lib/csv';
import styles from './tracking.module.css';

// --- Label maps ---

const PLATFORM_LABELS: Record<DestinationPlatform, string> = {
  meta_capi: 'Meta CAPI',
  tiktok_events: 'TikTok Events',
  ga4_mp: 'GA4 Measurement Protocol',
};

const STATUS_LABELS: Record<EventStatus, string> = {
  received: 'Alındı',
  forwarded: 'İletildi',
  no_consent: 'Rıza Yok',
  error: 'Hata',
};

const ALL_STATUSES: EventStatus[] = ['received', 'forwarded', 'no_consent', 'error'];

const RAW_STATUS_LABELS: Record<string, string> = {
  received: 'Alındı',
  forwarded: 'İletildi',
  failed: 'Hata',
  skipped_no_consent: 'Rıza Engellendi',
  duplicate: 'Yinelenen',
  disabled: 'Kapalı',
};
const RAW_STATUS_NORM: Record<string, EventStatus> = {
  received: 'received',
  forwarded: 'forwarded',
  failed: 'error',
  skipped_no_consent: 'no_consent',
  duplicate: 'received',
  disabled: 'received',
};

const PAGE_SIZE = 25;
type DetailTab = 'kurulum' | 'olay-kalitesi' | 'olay-gunlugu';

// --- Data-quality thresholds (server-side conversion / CAPI health) ---
// Error rate = failed / total events. Consent-block rate = skipped_no_consent / total.
// Match-quality (EMQ) score is 0..100. These bounds drive the red/amber warnings so a
// user never has to eyeball raw counts to notice a broken feed.
const ERR_RATE_CRITICAL = 0.1; // ≥10% iletilemedi → kırmızı
const ERR_RATE_WARNING = 0.03; // ≥3% iletilemedi → turuncu
const CONSENT_BLOCK_WARNING = 0.3; // ≥30% rıza yok → turuncu (dönüşüm sinyali kaybı)
const MQ_SCORE_CRITICAL = 30; // <30 zayıf eşleşme → kırmızı
const MQ_SCORE_WARNING = 60; // <60 orta eşleşme → turuncu

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('tr-TR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

function fmtShortDate(iso: string): string {
  return iso.slice(5).replace('-', '/');
}

// Format a 0..1 fraction as a Turkish percentage with one decimal (e.g. 0.104 → "%10,4").
function fmtPct1(fraction: number): string {
  return (
    '%' +
    (fraction * 100).toLocaleString('tr-TR', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })
  );
}

// --- CopyButton ---

function CopyButton({ text, label = 'Kopyala' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function handleCopy() {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const el = document.createElement('textarea');
      el.value = text; el.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(el); el.select();
      document.execCommand('copy'); document.body.removeChild(el);
    }
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  }
  return (
    <button className={`${styles.copyBtn} ${copied ? styles.copyBtnCopied : ''}`} onClick={handleCopy}>
      {copied ? 'Kopyalandı!' : label}
    </button>
  );
}

// --- Snippet copy button (dark block) ---

function SnippetCopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function handleCopy() {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const el = document.createElement('textarea');
      el.value = text; el.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(el); el.select();
      document.execCommand('copy'); document.body.removeChild(el);
    }
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  }
  return (
    <button className={`${styles.snippetCopyBtn} ${copied ? styles.snippetCopyBtnCopied : ''}`} onClick={handleCopy}>
      {copied ? 'Kopyalandı!' : 'Kopyala'}
    </button>
  );
}

// --- Status badge ---

function StatusBadge({ status, label }: { status: EventStatus; label?: string }) {
  const cls: Record<EventStatus, string> = {
    received: styles.statusReceived, forwarded: styles.statusForwarded,
    no_consent: styles.statusNoConsent, error: styles.statusError,
  };
  return (
    <span className={`${styles.statusBadge} ${cls[status] ?? ''}`}>
      {label ?? STATUS_LABELS[status] ?? status}
    </span>
  );
}

// --- Health KPI summary chips ---

function HealthSummary({ stats, loading }: { stats: TrackingStats | null; loading: boolean }) {
  if (loading) {
    return (
      <div className={styles.healthSummary}>
        <span className={`${styles.kpiChip} ${styles.kpiChipInfo}`}>Yükleniyor...</span>
      </div>
    );
  }
  if (!stats) return null;
  const total = stats.totals.total_events;
  const errRate = total > 0 ? stats.totals.total_errors / total : 0;
  // Rate-aware severity: a handful of errors in a large volume is not "red".
  const errChipClass =
    errRate >= ERR_RATE_CRITICAL
      ? styles.kpiChipErr
      : errRate >= ERR_RATE_WARNING
        ? styles.kpiChipWarn
        : styles.kpiChipOk;
  return (
    <div className={styles.healthSummary}>
      <span className={`${styles.kpiChip} ${styles.kpiChipInfo}`}>
        {total.toLocaleString('tr-TR')} Toplam Olay
      </span>
      <span className={`${styles.kpiChip} ${errChipClass}`}>
        {stats.totals.total_errors.toLocaleString('tr-TR')} Hata
        {total > 0 && stats.totals.total_errors > 0 ? ` · ${fmtPct1(errRate)}` : ''}
      </span>
    </div>
  );
}

// --- Çerez Rıza Değişkeni card ---

function CookieConsentCard({ source, onSaved }: { source: TrackingSource; onSaved: (u: TrackingSource) => void }) {
  const [value, setValue] = useState(source.consent_cookie_var ?? '');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    setValue(source.consent_cookie_var ?? '');
    setSaveError(null); setSaveSuccess(false);
  }, [source.id, source.consent_cookie_var]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault(); setSaving(true); setSaveError(null); setSaveSuccess(false);
    try {
      const updated = await patchTrackingSource(source.id, { consent_cookie_var: value.trim() || null });
      onSaved(updated); setSaveSuccess(true); setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setSaveError(parseApiError(err));
    } finally { setSaving(false); }
  }

  return (
    <div className={styles.consentCookieCard}>
      <div className={styles.consentCookieHeader}>
        <span className={styles.consentCookieTitle}>Çerez Rıza Değişkeni</span>
        {Boolean(source.consent_cookie_var) && <span className={styles.consentCookieSetBadge}>Ayarlı</span>}
      </div>
      <p className={styles.consentCookieDesc}>
        Sitenizin çerez/rıza durumunu tutan JavaScript değişkeninin adını girin; AYAZ bu değişkeni
        okuyup yalnızca rıza verildiğinde olayları iletir. Değişken{' '}
        <code className={styles.consentCookieCode}>&apos;true&apos;</code> veya{' '}
        <code className={styles.consentCookieCode}>&apos;1&apos;</code> ise rıza verilmiş kabul edilir;
        yok ya da <code className={styles.consentCookieCode}>&apos;false&apos;</code>/
        <code className={styles.consentCookieCode}>&apos;0&apos;</code> ise olay iletilmez.
      </p>
      <form className={styles.consentCookieForm} onSubmit={handleSave}>
        <input className={styles.input} placeholder="örn. window.cookieConsent" value={value}
          onChange={(e) => setValue(e.target.value)} disabled={saving} aria-label="Çerez rıza değişkeni adı" />
        <button type="submit" className={styles.primaryBtn} disabled={saving} aria-label="Kaydet">
          {saving ? 'Kaydediliyor...' : 'Kaydet'}
        </button>
      </form>
      {saveError && <span className={styles.formError} role="alert">{saveError}</span>}
      {saveSuccess && (
        <span className={styles.consentCookieSuccess} role="status">
          Kaydedildi. {value.trim() ? 'Snippet artık bu değişkeni okuyacak.' : 'Rıza değişkeni kaldırıldı.'}
        </span>
      )}
      {!value.trim() && !saveSuccess && (
        <span className={styles.consentCookieEmpty}>
          Henüz bir değişken tanımlanmadı — tüm olaylar platform varsayılanına göre iletilir.
        </span>
      )}
    </div>
  );
}

// --- Per-destination Zorunlu Rıza Sinyalleri panel ---

function DestConsentSignals({ dest, onSaved }: { dest: TrackingDestination; onSaved: (u: TrackingDestination) => void }) {
  const platformDefaults = PLATFORM_DEFAULT_CONSENT[dest.platform] ?? [];
  const isUsingDefault = !dest.required_consent || dest.required_consent.length === 0;
  const [selected, setSelected] = useState<Set<ConsentSignal>>(
    () => new Set(isUsingDefault ? platformDefaults : (dest.required_consent ?? [])),
  );
  const [isCustom, setIsCustom] = useState(!isUsingDefault);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    const usingDefault = !dest.required_consent || dest.required_consent.length === 0;
    setIsCustom(!usingDefault);
    setSelected(new Set(usingDefault ? platformDefaults : (dest.required_consent ?? [])));
    setSaveError(null); setSaveSuccess(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dest.id, dest.required_consent]);

  function toggleSignal(signal: ConsentSignal) {
    setSelected((prev) => { const n = new Set(prev); n.has(signal) ? n.delete(signal) : n.add(signal); return n; });
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault(); setSaving(true); setSaveError(null); setSaveSuccess(false);
    try {
      const payload: ConsentSignal[] | null = isCustom ? (Array.from(selected) as ConsentSignal[]) : null;
      const updated = await patchDestination(dest.id, { required_consent: payload });
      onSaved(updated); setSaveSuccess(true); setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setSaveError(parseApiError(err));
    } finally { setSaving(false); }
  }

  return (
    <div className={styles.destConsentPanel}>
      <div className={styles.destConsentTitle}>Zorunlu Rıza Sinyalleri</div>
      <form onSubmit={handleSave}>
        <div className={styles.destConsentModeRow}>
          <label className={styles.destConsentModeLabel}>
            <input type="radio" name={`consent-mode-${dest.id}`} checked={!isCustom}
              onChange={() => { setIsCustom(false); setSelected(new Set(platformDefaults)); }} disabled={saving} />
            <span>Varsayılan</span>
          </label>
          <label className={styles.destConsentModeLabel}>
            <input type="radio" name={`consent-mode-${dest.id}`} checked={isCustom}
              onChange={() => setIsCustom(true)} disabled={saving} />
            <span>Özel</span>
          </label>
        </div>
        <div className={styles.destConsentSignalGrid}>
          {ALL_CONSENT_SIGNALS.map((signal) => {
            const isDefault = platformDefaults.includes(signal);
            const checked = isCustom ? selected.has(signal) : isDefault;
            const isDefaultIndicator = !isCustom && isDefault;
            return (
              <label key={signal} className={`${styles.destConsentSignalLabel} ${isDefaultIndicator ? styles.destConsentSignalDefault : ''} ${!isCustom ? styles.destConsentSignalReadonly : ''}`}>
                <input type="checkbox" checked={checked} onChange={() => isCustom && toggleSignal(signal)}
                  disabled={saving || !isCustom} aria-label={CONSENT_SIGNAL_LABELS[signal]} />
                <span className={styles.destConsentSignalText}>
                  {CONSENT_SIGNAL_LABELS[signal]}
                  {isDefaultIndicator && <span className={styles.destConsentVarsayilan}> (varsayılan)</span>}
                </span>
              </label>
            );
          })}
        </div>
        <div className={styles.destConsentActions}>
          <button type="submit" className={styles.primaryBtn} disabled={saving} aria-label="Rıza sinyallerini kaydet">
            {saving ? 'Kaydediliyor...' : 'Kaydet'}
          </button>
          {saveSuccess && <span className={styles.consentCookieSuccess} role="status">Kaydedildi.</span>}
          {saveError && <span className={styles.formError} role="alert">{saveError}</span>}
        </div>
      </form>
    </div>
  );
}

// --- Data Quality Alerts ---
// Threshold-driven red/amber banners so a broken or degraded feed is impossible to
// miss: high delivery-error rate, high consent-loss rate, and low match quality.

type AlertSeverity = 'critical' | 'warning';

interface QualityAlert {
  severity: AlertSeverity;
  title: string;
  detail: string;
}

function computeQualityAlerts(stats: TrackingStats): QualityAlert[] {
  const alerts: QualityAlert[] = [];
  const total = stats.totals.total_events;
  if (total <= 0) return alerts;

  // 1) Delivery error rate
  const errRate = stats.totals.total_errors / total;
  if (errRate >= ERR_RATE_CRITICAL) {
    const perm = stats.deliverability?.permanent ?? 0;
    const permNote =
      perm > 0
        ? ` Bunların ${perm.toLocaleString('tr-TR')} tanesi kalıcı hata — hedef kimlik/yapılandırması düzeltilmeli.`
        : '';
    alerts.push({
      severity: 'critical',
      title: `İletim hata oranı yüksek: ${fmtPct1(errRate)}`,
      detail: `${stats.totals.total_errors.toLocaleString('tr-TR')} olay hedeflere iletilemedi. Olay Günlüğü'nden hata detaylarını inceleyin; geçici hataları "Yeniden Gönder" ile tekrar deneyin.${permNote}`,
    });
  } else if (errRate >= ERR_RATE_WARNING) {
    alerts.push({
      severity: 'warning',
      title: `Hata oranı beklenenden yüksek: ${fmtPct1(errRate)}`,
      detail: `${stats.totals.total_errors.toLocaleString('tr-TR')} olay iletilemedi. Geçici hatalar için "Yeniden Gönder", kalıcı hatalar için hedef yapılandırmasını kontrol edin.`,
    });
  }

  // 2) Consent-blocked rate — high loss usually signals a mis-wired consent banner
  const blockRate = stats.totals.consent_blocked / total;
  if (blockRate >= CONSENT_BLOCK_WARNING) {
    alerts.push({
      severity: 'warning',
      title: `Olayların ${fmtPct1(blockRate)}'i rıza olmadığı için iletilmedi`,
      detail: `${stats.totals.consent_blocked.toLocaleString('tr-TR')} olay KVKK rıza sinyali gelmediği için hedeflere gönderilmedi; bu, dönüşüm ölçümünde sinyal kaybına yol açar. Rıza banner'ınızın Consent Mode sinyallerini doğru gönderdiğini ve "Çerez Rıza Değişkeni" ayarını kontrol edin.`,
    });
  }

  // 3) Match quality (EMQ) — weak identity signals hurt attribution
  const mq = stats.match_quality;
  if (mq && mq.scored_events > 0) {
    if (mq.avg_score < MQ_SCORE_CRITICAL) {
      alerts.push({
        severity: 'critical',
        title: `Eşleşme kalitesi düşük: ${mq.avg_score}/100`,
        detail:
          'Kimlik sinyalleri zayıf olduğundan platformlar dönüşümleri kullanıcılarla yeterince eşleştiremiyor. Aşağıdaki "Eşleşme Kalitesi" bölümündeki eksik sinyalleri (e-posta, telefon, tıklama kimliği) tamamlayın.',
      });
    } else if (mq.avg_score < MQ_SCORE_WARNING) {
      alerts.push({
        severity: 'warning',
        title: `Eşleşme kalitesi geliştirilebilir: ${mq.avg_score}/100`,
        detail:
          'Daha fazla kimlik sinyali göndererek atıf doğruluğunu artırabilirsiniz. Aşağıdaki "Eşleşme Kalitesi" bölümündeki önerilere bakın.',
      });
    }
  }

  return alerts;
}

function DataQualityAlerts({ stats, loading }: { stats: TrackingStats | null; loading: boolean }) {
  if (loading || !stats || stats.totals.total_events <= 0) return null;
  const alerts = computeQualityAlerts(stats);
  if (alerts.length === 0) {
    return (
      <div className={`${styles.dqAlert} ${styles.dqAlertOk}`}>
        <span className={styles.dqAlertIcon} aria-hidden="true">✓</span>
        <div className={styles.dqAlertBody}>
          <div className={styles.dqAlertTitle}>Veri kalitesi sağlıklı</div>
          <div className={styles.dqAlertDetail}>
            Hata oranı, rıza kaybı ve eşleşme kalitesi normal aralıkta — iletim sağlıklı çalışıyor.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className={styles.dqAlertStack} role="alert">
      {alerts.map((a, i) => (
        <div
          key={i}
          className={`${styles.dqAlert} ${a.severity === 'critical' ? styles.dqAlertCritical : styles.dqAlertWarning}`}
        >
          <span className={styles.dqAlertIcon} aria-hidden="true">
            {a.severity === 'critical' ? '⚠' : '!'}
          </span>
          <div className={styles.dqAlertBody}>
            <div className={styles.dqAlertTitle}>{a.title}</div>
            <div className={styles.dqAlertDetail}>{a.detail}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

// --- Delivery Health panel ---

function DeliveryHealthPanel({ stats, loading, error, dateFrom, dateTo, activePreset, onSelectPreset }: {
  stats: TrackingStats | null; loading: boolean; error: string | null;
  dateFrom: string; dateTo: string; activePreset: PresetKey | null;
  onSelectPreset: (from: string, to: string) => void;
}) {
  return (
    <SectionCard
      title="İletim Sağlığı"
      right={
        <div className={styles.healthHeaderRight}>
          <DateRangePresets onSelect={onSelectPreset} activePreset={activePreset} />
          <span className={styles.dateRangeLabel}>{dateFrom} — {dateTo}</span>
        </div>
      }
    >
      {loading ? (
        <div className={styles.stateBoxSm}><span className={styles.muted}>İstatistikler yükleniyor...</span></div>
      ) : error ? (
        <div className={styles.stateBoxSm}><span className={styles.errorText}>{error}</span></div>
      ) : stats ? (
        <div className={styles.statCards}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{stats.totals.total_events.toLocaleString('tr-TR')}</div>
            <div className={styles.statLabel}>Toplam Olay</div>
          </div>
          <div className={`${styles.statCard} ${stats.totals.total_errors > 0 ? styles.statCardError : ''}`}>
            <div className={`${styles.statValue} ${stats.totals.total_errors > 0 ? styles.statValueError : ''}`}>
              {stats.totals.total_errors.toLocaleString('tr-TR')}
            </div>
            <div className={styles.statLabel}>Hata</div>
            {stats.deliverability && stats.deliverability.failed > 0 && (
              <div className={styles.deliverabilityNote}>
                {stats.deliverability.transient} geçici · {stats.deliverability.permanent} kalıcı
              </div>
            )}
          </div>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{stats.totals.consent_blocked.toLocaleString('tr-TR')}</div>
            <div className={styles.statLabel}>Rıza ile Engellenen</div>
          </div>
          <div className={styles.statCardBreakdown}>
            <div className={styles.statLabel} style={{ marginBottom: '0.5rem' }}>Duruma Göre</div>
            {Object.entries(stats.totals.by_status).map(([status, count]) => (
              <div key={status} className={styles.byStatusRow}>
                <StatusBadge status={RAW_STATUS_NORM[status] ?? 'received'} label={RAW_STATUS_LABELS[status] ?? status} />
                <span className={styles.byStatusCount}>{(count as number).toLocaleString('tr-TR')}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </SectionCard>
  );
}

// --- Inline bar sparkline ---

function EventSparkline({ daily, eventName }: { daily: import('@/lib/tracking-api').DailyPoint[]; eventName: string }) {
  const pts = daily.slice(-14).map((d) => ({ date: fmtShortDate(d.date), count: d.count }));
  if (pts.length === 0) return <span className={styles.muted}>—</span>;
  const maxCount = Math.max(...pts.map((p) => p.count), 1);
  return (
    <div className={styles.sparklineWrap} title={`${eventName} günlük trend`} aria-label={`${eventName} günlük trend`}>
      {pts.map((p, i) => {
        const h = Math.max(2, Math.round((p.count / maxCount) * 28));
        return <div key={i} className={styles.sparkBar} style={{ height: `${h}px` }} title={`${p.date}: ${p.count}`} />;
      })}
    </div>
  );
}

// --- Event Distribution table ---

function EventDistributionPanel({ sourceId, stats, loading, error, onStatsRefetch }: {
  sourceId: string; stats: TrackingStats | null; loading: boolean; error: string | null; onStatsRefetch: () => void;
}) {
  const [enabledOverrides, setEnabledOverrides] = useState<Record<string, boolean>>({});
  const [togglingEvents, setTogglingEvents] = useState<Set<string>>(new Set());

  useEffect(() => { setEnabledOverrides({}); }, [sourceId]);

  async function handleToggle(ev: EventStat, newEnabled: boolean) {
    const name = ev.event_name;
    setEnabledOverrides((prev) => ({ ...prev, [name]: newEnabled }));
    setTogglingEvents((prev) => new Set(prev).add(name));
    try { await toggleEventConfig(sourceId, name, newEnabled); onStatsRefetch(); }
    catch (err) { setEnabledOverrides((prev) => ({ ...prev, [name]: !newEnabled })); alert(parseApiError(err)); }
    finally {
      setTogglingEvents((prev) => { const n = new Set(prev); n.delete(name); return n; });
    }
  }

  const sorted = stats ? [...stats.by_event].sort((a, b) => b.count - a.count) : [];

  return (
    <SectionCard title="Olay Dağılımı">
      {loading ? (
        <div className={styles.stateBoxSm}><span className={styles.muted}>Yükleniyor...</span></div>
      ) : error ? (
        <div className={styles.stateBoxSm}><span className={styles.errorText}>{error}</span></div>
      ) : sorted.length === 0 ? (
        <div className={styles.stateBoxSm}><span className={styles.muted}>Bu dönemde olay verisi yok.</span></div>
      ) : (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Olay</th>
                  <th style={{ textAlign: 'center' }}>Durum</th>
                  <th style={{ textAlign: 'right' }}>Adet</th>
                  <th style={{ textAlign: 'right' }}>Hata</th>
                  <th>Günlük Trend</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((ev) => {
                  const isEnabled = ev.event_name in enabledOverrides ? enabledOverrides[ev.event_name] : (ev.enabled ?? true);
                  const isToggling = togglingEvents.has(ev.event_name);
                  return (
                    <tr key={ev.event_name} className={isEnabled ? undefined : styles.eventRowDisabled}>
                      <td className={styles.eventNameCell}>{ev.event_name}</td>
                      <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <div className={styles.eventToggleCell}>
                          <button
                            role="switch" aria-checked={isEnabled} disabled={isToggling}
                            aria-label={isEnabled ? `${ev.event_name} olayını CAPI'ye göndermeyi durdur` : `${ev.event_name} olayını CAPI'ye göndermeye başlat`}
                            className={`${styles.eventToggleSwitch} ${isEnabled ? styles.eventToggleSwitchOn : ''} ${isToggling ? styles.eventToggleSwitchBusy : ''}`}
                            onClick={() => handleToggle(ev, !isEnabled)}
                          >
                            <span className={styles.eventToggleKnob} />
                          </button>
                          <span className={isEnabled ? styles.eventToggleLabelOn : styles.eventToggleLabelOff}>
                            {isEnabled ? 'Açık' : 'Kapalı'}
                          </span>
                        </div>
                      </td>
                      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', opacity: isEnabled ? 1 : 0.45 }}>
                        {ev.count.toLocaleString('tr-TR')}
                      </td>
                      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: ev.errors > 0 ? 'var(--color-critical)' : undefined, opacity: isEnabled ? 1 : 0.45 }}>
                        {ev.errors > 0 ? ev.errors.toLocaleString('tr-TR') : '—'}
                      </td>
                      <td style={{ opacity: isEnabled ? 1 : 0.35 }}>
                        <EventSparkline daily={stats?.daily ?? []} eventName={ev.event_name} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {stats && stats.daily.length > 0 && (
            <div className={styles.dailyChartWrap}>
              <div className={styles.dailyChartTitle}>Günlük Olay Grafiği</div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={stats.daily.map((d) => ({ date: fmtShortDate(d.date), count: d.count, errors: d.errors }))}
                  margin={{ top: 4, right: 12, left: 0, bottom: 0 }} barCategoryGap="30%">
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} tickLine={false} axisLine={false} width={36}
                    tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)} />
                  <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid var(--color-border)', fontSize: 12, background: 'var(--color-surface)', color: 'var(--color-text)' }}
                    formatter={(value: number, name: string) => [value.toLocaleString('tr-TR'), name === 'count' ? 'Olay' : 'Hata']}
                    labelFormatter={(label: string) => `Tarih: ${label}`} />
                  <Bar dataKey="count" fill="var(--color-primary)" radius={[3, 3, 0, 0]} name="count" />
                  <Bar dataKey="errors" fill="var(--color-critical)" radius={[3, 3, 0, 0]} name="errors" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}

// --- Match Quality panel ---

const MATCH_TIP_BY_FIELD: Record<string, string> = {
  em: 'E-posta gönderimini artır — en güçlü ve en kararlı eşleşme sinyali.',
  ph: 'Telefon numarası ekle — yüksek eşleşme katkısı sağlar.',
  fbc: 'Meta tıklama kimliğini (fbc / fbclid) ilet — atıf kalitesini belirgin artırır.',
  fbp: 'Tarayıcı kimliğini (_fbp çerezi) ilet.',
  external_id: 'Kendi müşteri kimliğini (external_id) gönder — giriş yapan kullanıcılar için ideal.',
  client_ip_address: 'IP adresini sunucu tarafında ilet.',
  client_user_agent: 'Tarayıcı bilgisini (user agent) ilet.',
};

function mqScoreClass(score: number): string {
  if (score >= 60) return styles.mqScoreGood;
  if (score >= 30) return styles.mqScoreMid;
  return styles.mqScoreWeak;
}
function mqTierFillClass(tier: string): string {
  switch (tier) {
    case 'excellent': return styles.mqFillExcellent;
    case 'good': return styles.mqFillGood;
    case 'medium': return styles.mqFillMedium;
    default: return styles.mqFillWeak;
  }
}
function mqCoverageFillClass(pct: number): string {
  if (pct >= 70) return styles.mqFillGood;
  if (pct >= 40) return styles.mqFillMedium;
  return styles.mqFillWeak;
}
function mqScoreTier(score: number): string {
  if (score >= 85) return 'excellent';
  if (score >= 60) return 'good';
  if (score >= 30) return 'medium';
  return 'weak';
}
function mqTips(mq: MatchQualityStats): string[] {
  return mq.field_coverage.filter((f) => f.weight >= 10 && f.coverage_pct < 70).slice(0, 3)
    .map((f) => MATCH_TIP_BY_FIELD[f.key] ?? `${MATCH_FIELD_LABELS[f.key] ?? f.key} kapsamasını artır (şu an %${f.coverage_pct}).`);
}

function MatchQualityPanel({ stats, loading, error }: { stats: TrackingStats | null; loading: boolean; error: string | null }) {
  const mq = stats?.match_quality ?? null;
  const tips = mq ? mqTips(mq) : [];
  return (
    <SectionCard title="Eşleşme Kalitesi" right={mq ? <span className={styles.dateRangeLabel}>{mq.scored_events.toLocaleString('tr-TR')} skorlanan olay</span> : undefined}>
      {loading ? (
        <div className={styles.stateBoxSm}><span className={styles.muted}>Eşleşme kalitesi yükleniyor...</span></div>
      ) : error ? (
        <div className={styles.stateBoxSm}><span className={styles.errorText}>{error}</span></div>
      ) : !mq ? (
        <div className={styles.stateBoxSm}><span className={styles.muted}>Bu aralıkta eşleşme kalitesi skoru bulunan olay yok.</span></div>
      ) : (
        <>
          <div className={styles.mqLayout}>
            <div className={styles.mqScoreCol}>
              <div className={styles.mqGauge}>
                <span className={`${styles.mqScoreValue} ${mqScoreClass(mq.avg_score)}`}>{mq.avg_score}</span>
                <span className={styles.mqScoreOutOf}>/ 100</span>
              </div>
              <span className={`${styles.mqTierBadge} ${mqTierFillClass(mqScoreTier(mq.avg_score))}`}>
                {MATCH_TIER_LABELS[mqScoreTier(mq.avg_score)]}
              </span>
              <div className={styles.mqScoreLabel}>Ortalama Eşleşme Skoru</div>
              <div className={styles.mqTierDist}>
                {MATCH_TIER_ORDER.map((t) => {
                  const c = mq.tier_distribution[t] ?? 0;
                  const pct = mq.scored_events ? Math.round((c * 100) / mq.scored_events) : 0;
                  return (
                    <div key={t} className={styles.mqTierRow}>
                      <span className={styles.mqTierName}>{MATCH_TIER_LABELS[t]}</span>
                      <div className={styles.mqBarTrack}><div className={`${styles.mqBarFill} ${mqTierFillClass(t)}`} style={{ width: `${pct}%` }} /></div>
                      <span className={styles.mqTierCount}>{c.toLocaleString('tr-TR')}</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div className={styles.mqCoverageCol}>
              <div className={styles.mqColTitle}>Sinyal Kapsaması</div>
              {mq.field_coverage.map((f) => (
                <div key={f.key} className={styles.mqCovRow}>
                  <span className={styles.mqCovLabel}>{MATCH_FIELD_LABELS[f.key] ?? f.key}</span>
                  <div className={styles.mqBarTrack}><div className={`${styles.mqBarFill} ${mqCoverageFillClass(f.coverage_pct)}`} style={{ width: `${f.coverage_pct}%` }} /></div>
                  <span className={styles.mqCovPct}>%{f.coverage_pct}</span>
                </div>
              ))}
            </div>
          </div>
          {tips.length > 0 && (
            <div className={styles.mqTips}>
              <div className={styles.mqTipsTitle}>İyileştirme Önerileri</div>
              <ul className={styles.mqTipsList}>{tips.map((t, i) => <li key={i}>{t}</li>)}</ul>
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}

// --- Destination config ---

interface DestCfgState {
  meta_pixel_id: string; meta_access_token: string;
  tiktok_pixel_id: string; tiktok_access_token: string;
  ga4_measurement_id: string; ga4_api_secret: string;
}
const DEFAULT_DEST_CFG: DestCfgState = {
  meta_pixel_id: '', meta_access_token: '',
  tiktok_pixel_id: '', tiktok_access_token: '',
  ga4_measurement_id: '', ga4_api_secret: '',
};
function buildDestConfig(platform: DestinationPlatform, cfg: DestCfgState): Record<string, string> {
  switch (platform) {
    case 'meta_capi': return { pixel_id: cfg.meta_pixel_id, access_token: cfg.meta_access_token };
    case 'tiktok_events': return { pixel_id: cfg.tiktok_pixel_id, access_token: cfg.tiktok_access_token };
    case 'ga4_mp': return { measurement_id: cfg.ga4_measurement_id, api_secret: cfg.ga4_api_secret };
  }
}
function destConfigSummary(platform: DestinationPlatform, config: Record<string, string>): string {
  switch (platform) {
    case 'meta_capi': return `Pixel: ${config.pixel_id ?? '-'}`;
    case 'tiktok_events': return `Pixel: ${config.pixel_id ?? '-'}`;
    case 'ga4_mp': return `Measurement ID: ${config.measurement_id ?? '-'}`;
  }
}

function DestinationForm({ sourceId, onCreated, onCancel }: { sourceId: string; onCreated: () => void; onCancel: () => void }) {
  const [platform, setPlatform] = useState<DestinationPlatform>('meta_capi');
  const [cfg, setCfg] = useState<DestCfgState>({ ...DEFAULT_DEST_CFG });
  const [consentRequired, setConsentRequired] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  function updateCfg(key: keyof DestCfgState, value: string) { setCfg((prev) => ({ ...prev, [key]: value })); }
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setFormError(null); setSubmitting(true);
    try {
      await createDestination(sourceId, { platform, config: buildDestConfig(platform, cfg), consent_required: consentRequired });
      onCreated();
    } catch (err: unknown) { setFormError(parseApiError(err)); }
    finally { setSubmitting(false); }
  }
  return (
    <form className={styles.destForm} onSubmit={handleSubmit}>
      <div className={styles.destFormTitle}>Yeni Hedef Ekle</div>
      <div className={styles.formRow}>
        <div className={styles.field}>
          <label className={styles.label}>Platform</label>
          <select className={styles.select} value={platform} onChange={(e) => { setPlatform(e.target.value as DestinationPlatform); setCfg({ ...DEFAULT_DEST_CFG }); }} disabled={submitting}>
            {(Object.entries(PLATFORM_LABELS) as [DestinationPlatform, string][]).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
      </div>
      {platform === 'meta_capi' && (
        <div className={styles.formRow}>
          <div className={styles.field}><label className={styles.label}>Pixel ID</label><input className={styles.input} placeholder="123456789012345" value={cfg.meta_pixel_id} onChange={(e) => updateCfg('meta_pixel_id', e.target.value)} required disabled={submitting} /></div>
          <div className={styles.field}><label className={styles.label}>Access Token</label><input className={styles.input} type="password" placeholder="EAAxxxxxxx" value={cfg.meta_access_token} onChange={(e) => updateCfg('meta_access_token', e.target.value)} required disabled={submitting} /></div>
        </div>
      )}
      {platform === 'tiktok_events' && (
        <div className={styles.formRow}>
          <div className={styles.field}><label className={styles.label}>Pixel ID</label><input className={styles.input} placeholder="CXXXXXXXXXXXXXX" value={cfg.tiktok_pixel_id} onChange={(e) => updateCfg('tiktok_pixel_id', e.target.value)} required disabled={submitting} /></div>
          <div className={styles.field}><label className={styles.label}>Access Token</label><input className={styles.input} type="password" placeholder="TikTok Events API token" value={cfg.tiktok_access_token} onChange={(e) => updateCfg('tiktok_access_token', e.target.value)} required disabled={submitting} /></div>
        </div>
      )}
      {platform === 'ga4_mp' && (
        <div className={styles.formRow}>
          <div className={styles.field}><label className={styles.label}>Measurement ID</label><input className={styles.input} placeholder="G-XXXXXXXXXX" value={cfg.ga4_measurement_id} onChange={(e) => updateCfg('ga4_measurement_id', e.target.value)} required disabled={submitting} /></div>
          <div className={styles.field}><label className={styles.label}>API Secret</label><input className={styles.input} type="password" placeholder="GA4 Measurement Protocol API secret" value={cfg.ga4_api_secret} onChange={(e) => updateCfg('ga4_api_secret', e.target.value)} required disabled={submitting} /></div>
        </div>
      )}
      <div className={styles.consentRow}>
        <label className={styles.toggle} aria-label="KVKK rıza gerekli" onClick={(e) => e.stopPropagation()}>
          <input type="checkbox" checked={consentRequired} onChange={(e) => setConsentRequired(e.target.checked)} disabled={submitting} />
          <span className={styles.toggleSlider} />
        </label>
        <div>
          <div className={styles.consentLabel}>KVKK rıza gerekli</div>
          <div className={styles.consentDesc}>Açık ise bu hedefe yalnızca rıza veren kullanıcı olayları iletilir.</div>
        </div>
      </div>
      {formError && <span className={styles.formError}>{formError}</span>}
      <div className={styles.formRow}>
        <button type="submit" className={styles.primaryBtn} disabled={submitting}>{submitting ? 'Ekleniyor...' : 'Hedef Ekle'}</button>
        <button type="button" className={styles.secondaryBtn} onClick={onCancel} disabled={submitting}>Iptal</button>
      </div>
    </form>
  );
}

// --- Debug Console: filterable + paginated event log ---

function DebugConsole({ sourceId, eventNames }: { sourceId: string; eventNames: string[] }) {
  const [events, setEvents] = useState<TrackingEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<EventStatus | ''>('');
  const [filterEvent, setFilterEvent] = useState('');
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const fetchEvents = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const data = await getSourceEvents(sourceId, { status: filterStatus || undefined, event_name: filterEvent || undefined, limit: 200 });
      setEvents(data); setPage(1);
    } catch (err: unknown) { setError(parseApiError(err)); }
    finally { setLoading(false); }
  }, [sourceId, filterStatus, filterEvent]);

  useEffect(() => { fetchEvents(); }, [fetchEvents]);
  useEffect(() => { setPage(1); }, [filterStatus, filterEvent, sourceId]);

  async function handleRetry(ev: TrackingEvent) {
    if (!ev.id) return;
    setRetryingId(ev.id);
    try { await retryEvent(ev.id); await fetchEvents(); }
    catch (err: unknown) { setError(parseApiError(err)); }
    finally { setRetryingId(null); }
  }

  const totalPages = Math.max(1, Math.ceil(events.length / PAGE_SIZE));
  const pageEvents = events.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Export the currently-fetched (and filtered) event set so a data analyst can
  // hand a failing-events log to a developer without screen-scraping.
  function exportEvents() {
    const errCatTr: Record<string, string> = {
      transient: 'Geçici', permanent: 'Kalıcı', unknown: 'Bilinmiyor',
    };
    downloadRowsAsCsv(
      events.map((ev) => ({
        olay: ev.event_name,
        zaman: ev.event_time,
        durum: STATUS_LABELS[ev.status] ?? ev.status,
        iletim: ev.forwarded_count,
        yeniden_deneme: ev.retry_count ?? 0,
        hata_kategorisi: ev.error_category ? (errCatTr[ev.error_category] ?? ev.error_category) : '',
        hata_detayi: ev.error_detail ?? '',
      })),
      `olay-gunlugu-${sourceId}.csv`,
      [
        { key: 'olay', label: 'Olay Adı' },
        { key: 'zaman', label: 'Zaman' },
        { key: 'durum', label: 'Durum' },
        { key: 'iletim', label: 'İletim' },
        { key: 'yeniden_deneme', label: 'Yeniden Deneme' },
        { key: 'hata_kategorisi', label: 'Hata Kategorisi' },
        { key: 'hata_detayi', label: 'Hata Detayı' },
      ],
    );
  }

  return (
    <SectionCard
      title="Olay Günlüğü"
      right={
        <div className={styles.debugFilters}>
          <select className={styles.selectSm} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value as EventStatus | '')} aria-label="Durum filtresi">
            <option value="">Tüm Durumlar</option>
            {ALL_STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
          </select>
          <select className={styles.selectSm} value={filterEvent} onChange={(e) => setFilterEvent(e.target.value)} aria-label="Olay filtresi">
            <option value="">Tüm Olaylar</option>
            {eventNames.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <button className={styles.secondaryBtn} onClick={exportEvents} disabled={loading || events.length === 0} aria-label="Olay günlüğünü CSV indir">CSV</button>
          <button className={styles.secondaryBtn} onClick={fetchEvents} disabled={loading} aria-label="Yenile">{loading ? '...' : 'Yenile'}</button>
        </div>
      }
    >
      {loading ? (
        <div className={styles.stateBoxSm}><span className={styles.muted}>Olaylar yükleniyor...</span></div>
      ) : error ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.errorText}>{error}</span><br />
          <button className={styles.secondaryBtn} style={{ marginTop: '0.75rem' }} onClick={fetchEvents}>Tekrar Dene</button>
        </div>
      ) : events.length === 0 ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>{filterStatus || filterEvent ? 'Bu filtreyle eşleşen olay bulunamadı.' : 'Henüz kayıtlı olay yok.'}</span>
        </div>
      ) : (
        <>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead className={styles.stickyThead}>
                <tr>
                  <th>Olay Adı</th><th>Zaman</th><th>Durum</th><th>İletim</th><th>Hata Detayı</th><th>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {pageEvents.map((ev, idx) => (
                  <tr key={ev.id ?? idx}>
                    <td>{ev.event_name}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(ev.event_time)}</td>
                    <td><StatusBadge status={ev.status} /></td>
                    <td>
                      {ev.forwarded_count}
                      {(ev.retry_count ?? 0) > 0 && <span className={styles.retryCount} title="Yeniden deneme sayısı"> ↻{ev.retry_count}</span>}
                    </td>
                    <td>
                      {ev.error_detail ? (
                        <span className={styles.errorCell}>
                          {ev.error_category && (
                            <span className={ev.error_category === 'transient' ? styles.errCatTransient : ev.error_category === 'permanent' ? styles.errCatPermanent : styles.errCatUnknown}
                              title={ev.error_category === 'transient' ? 'Geçici hata — yeniden denenebilir' : ev.error_category === 'permanent' ? 'Kalıcı hata — yapılandırma/kimlik düzeltilmeli' : 'Sınıflandırılamayan hata'}>
                              {ev.error_category === 'transient' ? 'Geçici' : ev.error_category === 'permanent' ? 'Kalıcı' : 'Bilinmiyor'}
                            </span>
                          )}
                          <span className={styles.errorDetail} title={ev.error_detail}>
                            {ev.error_detail.length > 50 ? ev.error_detail.slice(0, 50) + '...' : ev.error_detail}
                          </span>
                        </span>
                      ) : <span className={styles.muted}>—</span>}
                    </td>
                    <td>
                      {ev.status === 'error' && ev.id ? (
                        <button className={styles.secondaryBtn} onClick={() => handleRetry(ev)} disabled={retryingId === ev.id}
                          title={ev.error_retryable ? 'Bu hata geçici — yeniden gönder' : 'Yeniden gönder (kalıcı hata olabilir)'}>
                          {retryingId === ev.id ? '...' : 'Yeniden Gönder'}
                        </button>
                      ) : <span className={styles.muted}>—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div className={styles.paginationRow}>
              <button className={styles.secondaryBtn} onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>&lsaquo; Önceki</button>
              <span className={styles.pageInfo}>Sayfa {page} / {totalPages}</span>
              <button className={styles.secondaryBtn} onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>Sonraki &rsaquo;</button>
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}

// --- Source detail panel with tabs ---

function SourceDetailPanel({ source: initialSource, onSourceUpdated }: { source: TrackingSource; onSourceUpdated?: (u: TrackingSource) => void }) {
  const [source, setSource] = useState<TrackingSource>(initialSource);
  const [activeTab, setActiveTab] = useState<DetailTab>('kurulum');
  const [snippetExpanded, setSnippetExpanded] = useState(false);

  useEffect(() => { setSource(initialSource); }, [initialSource]);

  const [snippetInfo, setSnippetInfo] = useState<SnippetInfo | null>(null);
  const [snippetLoading, setSnippetLoading] = useState(true);
  const [snippetError, setSnippetError] = useState<string | null>(null);

  const [destinations, setDestinations] = useState<TrackingDestination[]>([]);
  const [destLoading, setDestLoading] = useState(true);
  const [destError, setDestError] = useState<string | null>(null);
  const [showDestForm, setShowDestForm] = useState(false);
  const [deletingDestId, setDeletingDestId] = useState<string | null>(null);
  const [expandedDestIds, setExpandedDestIds] = useState<Set<string>>(new Set());

  const [stats, setStats] = useState<TrackingStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);

  const defaultRange = computePreset('son30');
  const [statsDateFrom, setStatsDateFrom] = useState(defaultRange.from);
  const [statsDateTo, setStatsDateTo] = useState(defaultRange.to);

  const collectUrl = getCollectUrl(source.public_token);

  const fetchSnippet = useCallback(async () => {
    setSnippetLoading(true); setSnippetError(null);
    try { const data = await getSourceSnippet(source.id); setSnippetInfo(data); }
    catch (err: unknown) { setSnippetError(parseApiError(err)); }
    finally { setSnippetLoading(false); }
  }, [source.id]);

  function handleSourceSaved(updated: TrackingSource) {
    setSource(updated); onSourceUpdated?.(updated); fetchSnippet();
  }

  const fetchDestinations = useCallback(async () => {
    setDestLoading(true); setDestError(null);
    try { const data = await getSourceDestinations(source.id); setDestinations(data); }
    catch (err: unknown) { setDestError(parseApiError(err)); }
    finally { setDestLoading(false); }
  }, [source.id]);

  const fetchStats = useCallback(async () => {
    setStatsLoading(true); setStatsError(null);
    try { const data = await getSourceStats(source.id, { date_from: statsDateFrom, date_to: statsDateTo }); setStats(data); }
    catch (err: unknown) { setStatsError(parseApiError(err)); }
    finally { setStatsLoading(false); }
  }, [source.id, statsDateFrom, statsDateTo]);

  useEffect(() => { fetchSnippet(); fetchDestinations(); }, [fetchSnippet, fetchDestinations]);
  useEffect(() => { fetchStats(); }, [fetchStats]);

  async function handleDeleteDest(id: string) {
    setDeletingDestId(id);
    try { await deleteDestination(id); await fetchDestinations(); }
    catch (err) { alert(parseApiError(err)); }
    finally { setDeletingDestId(null); }
  }

  const activePreset = detectPreset(statsDateFrom, statsDateTo);
  const eventNames = stats ? stats.by_event.map((e) => e.event_name) : [];

  const TAB_LABELS: Record<DetailTab, string> = {
    'kurulum': 'Kurulum',
    'olay-kalitesi': 'Olay Kalitesi',
    'olay-gunlugu': 'Olay Günlüğü',
  };

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>{source.name}</h2>
        <span className={styles.muted} style={{ fontSize: '0.8125rem' }}>{source.domain}</span>
      </div>

      {/* Health KPI chips — always visible */}
      <HealthSummary stats={stats} loading={statsLoading} />

      {/* Tab bar */}
      <div className={styles.tabBar}>
        {(Object.keys(TAB_LABELS) as DetailTab[]).map((tab) => (
          <button key={tab} className={`${styles.tabBtn} ${activeTab === tab ? styles.tabBtnActive : ''}`} onClick={() => setActiveTab(tab)}>
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* Tab: Kurulum */}
      {activeTab === 'kurulum' && (
        <div className={styles.tabContent}>
          <div className={styles.copyRow}>
            <span className={styles.copyRowLabel}>Collect URL</span>
            <span className={styles.copyRowValue} title={collectUrl}>{collectUrl}</span>
            <CopyButton text={collectUrl} />
          </div>

          <div className={styles.snippetToggleRow}>
            <button className={styles.snippetToggleBtn} onClick={() => setSnippetExpanded((v) => !v)} aria-expanded={snippetExpanded}>
              {snippetExpanded ? 'Snippet\'i Gizle' : 'Entegrasyon Snippet\'ini Göster'}
            </button>
          </div>
          {snippetExpanded && (
            <div className={styles.snippetBlock}>
              <div className={styles.snippetHeader}>
                <span className={styles.snippetLabel}>Entegrasyon Snippet</span>
                {snippetInfo && <SnippetCopyButton text={snippetInfo.snippet} />}
              </div>
              {snippetLoading ? (
                <code className={styles.snippetCode}>Yükleniyor...</code>
              ) : snippetError ? (
                <code className={styles.snippetCode} style={{ color: 'var(--color-critical)' }}>{snippetError}</code>
              ) : snippetInfo ? (
                <code className={styles.snippetCode}>{snippetInfo.snippet}</code>
              ) : null}
            </div>
          )}

          <CookieConsentCard source={source} onSaved={handleSourceSaved} />

          <SectionCard title="Hedefler">
            {destLoading ? (
              <div className={styles.stateBoxSm}><span className={styles.muted}>Hedefler yükleniyor...</span></div>
            ) : destError ? (
              <div className={styles.stateBoxSm}><span className={styles.errorText}>{destError}</span></div>
            ) : destinations.length === 0 && !showDestForm ? (
              <div className={styles.stateBoxSm}><span className={styles.muted}>Henüz hedef eklenmedi.</span></div>
            ) : (
              <div className={styles.destList}>
                {destinations.map((dest) => {
                  const isExpanded = expandedDestIds.has(dest.id);
                  return (
                    <div key={dest.id} className={styles.destCard}>
                      <div className={styles.destRow}>
                        <span className={styles.destPlatformBadge}>{PLATFORM_LABELS[dest.platform] ?? dest.platform}</span>
                        <span className={styles.destConfig}>{destConfigSummary(dest.platform, dest.config)}</span>
                        <span className={`${styles.consentBadge} ${dest.consent_required ? styles.consentOn : styles.consentOff}`}>
                          {dest.consent_required ? 'KVKK rıza' : 'Rıza yok'}
                        </span>
                        <button
                          className={styles.destExpandBtn}
                          aria-expanded={isExpanded}
                          onClick={() => setExpandedDestIds((prev) => {
                            const n = new Set(prev);
                            n.has(dest.id) ? n.delete(dest.id) : n.add(dest.id);
                            return n;
                          })}
                          aria-label={isExpanded ? 'Rıza sinyallerini gizle' : 'Rıza sinyallerini göster'}
                        >
                          {isExpanded ? '▲' : '▼'}
                        </button>
                        <button className={styles.dangerBtn} disabled={deletingDestId === dest.id} onClick={() => handleDeleteDest(dest.id)}>
                          {deletingDestId === dest.id ? '...' : 'Sil'}
                        </button>
                      </div>
                      {isExpanded && (
                        <DestConsentSignals dest={dest} onSaved={(updated) => setDestinations((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))} />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
            {showDestForm ? (
              <DestinationForm sourceId={source.id} onCreated={() => { setShowDestForm(false); fetchDestinations(); }} onCancel={() => setShowDestForm(false)} />
            ) : (
              <div className={styles.addBtnRow}>
                <button className={styles.secondaryBtn} onClick={() => setShowDestForm(true)}>+ Hedef Ekle</button>
              </div>
            )}
          </SectionCard>
        </div>
      )}

      {/* Tab: Olay Kalitesi */}
      {activeTab === 'olay-kalitesi' && (
        <div className={styles.tabContent}>
          <DataQualityAlerts stats={stats} loading={statsLoading} />
          <DeliveryHealthPanel stats={stats} loading={statsLoading} error={statsError}
            dateFrom={statsDateFrom} dateTo={statsDateTo} activePreset={activePreset}
            onSelectPreset={(from, to) => { setStatsDateFrom(from); setStatsDateTo(to); }} />
          <EventDistributionPanel sourceId={source.id} stats={stats} loading={statsLoading} error={statsError} onStatsRefetch={fetchStats} />
          <MatchQualityPanel stats={stats} loading={statsLoading} error={statsError} />
        </div>
      )}

      {/* Tab: Olay Günlüğü */}
      {activeTab === 'olay-gunlugu' && (
        <div className={styles.tabContent}>
          <DebugConsole sourceId={source.id} eventNames={eventNames} />
        </div>
      )}
    </div>
  );
}

// --- Main tracking page ---

export default function TrackingPage() {
  const router = useRouter();
  useEffect(() => { if (!getToken()) router.replace('/login'); }, [router]);

  const [sources, setSources] = useState<TrackingSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [showNewSource, setShowNewSource] = useState(false);
  const [nsName, setNsName] = useState('');
  const [nsDomain, setNsDomain] = useState('');
  const [nsSubmitting, setNsSubmitting] = useState(false);
  const [nsError, setNsError] = useState<string | null>(null);

  const fetchSources = useCallback(async () => {
    setSourcesLoading(true); setSourcesError(null);
    try {
      const data = await getTrackingSources();
      setSources(data);
      if (data.length > 0 && !selectedSourceId) setSelectedSourceId(data[0].id);
    } catch (err: unknown) { setSourcesError(parseApiError(err)); }
    finally { setSourcesLoading(false); }
  }, [selectedSourceId]);

  useEffect(() => {
    if (!getToken()) return;
    fetchSources();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreateSource(e: React.FormEvent) {
    e.preventDefault(); setNsError(null); setNsSubmitting(true);
    try {
      const created = await createTrackingSource({ name: nsName, domain: nsDomain });
      setSources((prev) => [...prev, created]); setSelectedSourceId(created.id);
      setNsName(''); setNsDomain(''); setShowNewSource(false);
    } catch (err: unknown) { setNsError(parseApiError(err)); }
    finally { setNsSubmitting(false); }
  }

  const selectedSource = sources.find((s) => s.id === selectedSourceId) ?? null;

  return (
    <div className={styles.shell}>
      <AppNav />
      <main className={styles.main}>
        <div>
          <h1 className={styles.pageTitle}>Ölçümleme</h1>
          <p className={styles.pageSubtitle}>
            Sunucu tarafı izleme kaynaklarınızı yönetin, hedef platformlara olay iletin ve KVKK uyumlu rıza akışlarını yapılandırın.
          </p>
        </div>

        <div className={styles.layout}>
          {/* Left: source list */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>İzleme Kaynakları</h2>
              {!showNewSource && (
                <button className={styles.secondaryBtn} onClick={() => setShowNewSource(true)}>+ Yeni Kaynak</button>
              )}
            </div>

            {showNewSource && (
              <form className={styles.formBox} onSubmit={handleCreateSource}>
                <div className={styles.field}>
                  <label className={styles.label}>Kaynak Adı</label>
                  <input className={styles.input} placeholder="Web Sitesi Ana" value={nsName} onChange={(e) => setNsName(e.target.value)} required disabled={nsSubmitting} />
                </div>
                <div className={styles.field}>
                  <label className={styles.label}>Domain</label>
                  <input className={styles.input} placeholder="example.com" value={nsDomain} onChange={(e) => setNsDomain(e.target.value)} required disabled={nsSubmitting} />
                </div>
                {nsError && <span className={styles.formError}>{nsError}</span>}
                <div className={styles.formRow}>
                  <button type="submit" className={styles.primaryBtn} disabled={nsSubmitting}>{nsSubmitting ? 'Olusturuluyor...' : 'Olustur'}</button>
                  <button type="button" className={styles.secondaryBtn} onClick={() => { setShowNewSource(false); setNsError(null); }} disabled={nsSubmitting}>Iptal</button>
                </div>
              </form>
            )}

            {sourcesLoading ? (
              <div className={styles.stateBox}><span className={styles.muted}>Yükleniyor...</span></div>
            ) : sourcesError ? (
              <div className={styles.stateBox}>
                <span className={styles.errorText}>{sourcesError}</span><br />
                <button className={styles.secondaryBtn} style={{ marginTop: '0.75rem' }} onClick={fetchSources}>Tekrar Dene</button>
              </div>
            ) : sources.length === 0 ? (
              <EmptyState title="Henüz izleme kaynağı yok" subtitle="Bir kaynak ekleyerek başlayın"
                action={{ label: '+ Yeni Kaynak', onClick: () => setShowNewSource(true) }} />
            ) : (
              <div className={styles.sourceList}>
                {sources.map((src) => (
                  <div key={src.id}
                    className={`${styles.sourceItem} ${selectedSourceId === src.id ? styles.sourceItemActive : ''}`}
                    onClick={() => setSelectedSourceId(src.id)} role="button" tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && setSelectedSourceId(src.id)}
                  >
                    <span className={`${styles.sourceDot} ${selectedSourceId === src.id ? styles.sourceDotActive : ''}`} />
                    <div className={styles.sourceInfo}>
                      <div className={styles.sourceName}>{src.name}</div>
                      <div className={styles.sourceMeta}>{src.domain}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right: detail panel */}
          <div>
            {selectedSource ? (
              <SourceDetailPanel source={selectedSource} />
            ) : (
              <div className={styles.card}>
                <div className={styles.stateBox}>
                  <span className={styles.muted}>{sourcesLoading ? 'Yükleniyor...' : 'Sol taraftan bir izleme kaynağı seçin.'}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
