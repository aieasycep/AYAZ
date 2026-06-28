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

// Raw backend status keys (as returned by the stats by_status breakdown) → TR label + color bucket.
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

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function fmtShortDate(iso: string): string {
  // YYYY-MM-DD → MM/DD
  return iso.slice(5).replace('-', '/');
}

// --- CopyButton (inline text) ---

function CopyButton({ text, label = 'Kopyala' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement('textarea');
      el.value = text;
      el.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      className={`${styles.copyBtn} ${copied ? styles.copyBtnCopied : ''}`}
      onClick={handleCopy}
    >
      {copied ? 'Kopyalandı!' : label}
    </button>
  );
}

// --- Snippet copy button (dark block) ---

function SnippetCopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement('textarea');
      el.value = text;
      el.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <button
      className={`${styles.snippetCopyBtn} ${copied ? styles.snippetCopyBtnCopied : ''}`}
      onClick={handleCopy}
    >
      {copied ? 'Kopyalandı!' : 'Kopyala'}
    </button>
  );
}

// --- Status badge ---

function StatusBadge({ status, label }: { status: EventStatus; label?: string }) {
  const cls: Record<EventStatus, string> = {
    received: styles.statusReceived,
    forwarded: styles.statusForwarded,
    no_consent: styles.statusNoConsent,
    error: styles.statusError,
  };
  return (
    <span className={`${styles.statusBadge} ${cls[status] ?? ''}`}>
      {label ?? STATUS_LABELS[status] ?? status}
    </span>
  );
}

// --- Çerez Rıza Değişkeni card ---

function CookieConsentCard({
  source,
  onSaved,
}: {
  source: TrackingSource;
  onSaved: (updated: TrackingSource) => void;
}) {
  const [value, setValue] = useState(source.consent_cookie_var ?? '');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Reset local state when source changes
  useEffect(() => {
    setValue(source.consent_cookie_var ?? '');
    setSaveError(null);
    setSaveSuccess(false);
  }, [source.id, source.consent_cookie_var]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const updated = await patchTrackingSource(source.id, {
        consent_cookie_var: value.trim() || null,
      });
      onSaved(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Kaydedilemedi');
    } finally {
      setSaving(false);
    }
  }

  const isSet = Boolean(source.consent_cookie_var);

  return (
    <div className={styles.consentCookieCard}>
      <div className={styles.consentCookieHeader}>
        <span className={styles.consentCookieTitle}>Çerez Rıza Değişkeni</span>
        {isSet && (
          <span className={styles.consentCookieSetBadge}>Ayarlı</span>
        )}
      </div>
      <p className={styles.consentCookieDesc}>
        Sitenizin çerez/rıza durumunu tutan JavaScript değişkeninin adını girin; AYAZ bu
        değişkeni okuyup yalnızca rıza verildiğinde olayları iletir. Değişken{' '}
        <code className={styles.consentCookieCode}>&apos;true&apos;</code> veya{' '}
        <code className={styles.consentCookieCode}>&apos;1&apos;</code> ise rıza verilmiş
        kabul edilir; yok ya da{' '}
        <code className={styles.consentCookieCode}>&apos;false&apos;</code>/{' '}
        <code className={styles.consentCookieCode}>&apos;0&apos;</code> ise olay
        iletilmez.
      </p>
      <form className={styles.consentCookieForm} onSubmit={handleSave}>
        <input
          className={styles.input}
          placeholder="örn. window.cookieConsent"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={saving}
          aria-label="Çerez rıza değişkeni adı"
        />
        <button
          type="submit"
          className={styles.primaryBtn}
          disabled={saving}
          aria-label="Çerez rıza değişkenini kaydet"
        >
          {saving ? 'Kaydediliyor...' : 'Kaydet'}
        </button>
      </form>
      {saveError && (
        <span className={styles.formError} role="alert">
          {saveError}
        </span>
      )}
      {saveSuccess && (
        <span className={styles.consentCookieSuccess} role="status">
          Kaydedildi.{' '}
          {value.trim()
            ? 'Snippet artık bu değişkeni okuyacak.'
            : 'Rıza değişkeni kaldırıldı.'}
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

function DestConsentSignals({
  dest,
  onSaved,
}: {
  dest: TrackingDestination;
  onSaved: (updated: TrackingDestination) => void;
}) {
  // Effective consent: null/empty means platform default is used
  const platformDefaults = PLATFORM_DEFAULT_CONSENT[dest.platform] ?? [];
  const isUsingDefault = !dest.required_consent || dest.required_consent.length === 0;

  // Local checkbox state — initialise from current required_consent or defaults
  const [selected, setSelected] = useState<Set<ConsentSignal>>(
    () => new Set(isUsingDefault ? platformDefaults : (dest.required_consent ?? [])),
  );
  const [isCustom, setIsCustom] = useState(!isUsingDefault);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Sync when dest prop changes (e.g. after a save from parent)
  useEffect(() => {
    const usingDefault = !dest.required_consent || dest.required_consent.length === 0;
    setIsCustom(!usingDefault);
    setSelected(
      new Set(usingDefault ? platformDefaults : (dest.required_consent ?? [])),
    );
    setSaveError(null);
    setSaveSuccess(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dest.id, dest.required_consent]);

  function toggleSignal(signal: ConsentSignal) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(signal)) {
        next.delete(signal);
      } else {
        next.add(signal);
      }
      return next;
    });
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      // When "use default" mode: send null/empty to restore platform default
      const payload: ConsentSignal[] | null = isCustom
        ? (Array.from(selected) as ConsentSignal[])
        : null;
      const updated = await patchDestination(dest.id, { required_consent: payload });
      onSaved(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Kaydedilemedi');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.destConsentPanel}>
      <div className={styles.destConsentTitle}>Zorunlu Rıza Sinyalleri</div>
      <form onSubmit={handleSave}>
        <div className={styles.destConsentModeRow}>
          <label className={styles.destConsentModeLabel}>
            <input
              type="radio"
              name={`consent-mode-${dest.id}`}
              checked={!isCustom}
              onChange={() => {
                setIsCustom(false);
                setSelected(new Set(platformDefaults));
              }}
              disabled={saving}
            />
            <span>Varsayılan</span>
          </label>
          <label className={styles.destConsentModeLabel}>
            <input
              type="radio"
              name={`consent-mode-${dest.id}`}
              checked={isCustom}
              onChange={() => setIsCustom(true)}
              disabled={saving}
            />
            <span>Özel</span>
          </label>
        </div>

        <div className={styles.destConsentSignalGrid}>
          {ALL_CONSENT_SIGNALS.map((signal) => {
            const isDefault = platformDefaults.includes(signal);
            const checked = isCustom ? selected.has(signal) : isDefault;
            const isDefaultIndicator = !isCustom && isDefault;
            return (
              <label
                key={signal}
                className={`${styles.destConsentSignalLabel} ${
                  isDefaultIndicator ? styles.destConsentSignalDefault : ''
                } ${!isCustom ? styles.destConsentSignalReadonly : ''}`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => isCustom && toggleSignal(signal)}
                  disabled={saving || !isCustom}
                  aria-label={CONSENT_SIGNAL_LABELS[signal]}
                />
                <span className={styles.destConsentSignalText}>
                  {CONSENT_SIGNAL_LABELS[signal]}
                  {isDefaultIndicator && (
                    <span className={styles.destConsentVarsayilan}> (varsayılan)</span>
                  )}
                </span>
              </label>
            );
          })}
        </div>

        <div className={styles.destConsentActions}>
          <button
            type="submit"
            className={styles.primaryBtn}
            disabled={saving}
            aria-label="Rıza sinyallerini kaydet"
          >
            {saving ? 'Kaydediliyor...' : 'Kaydet'}
          </button>
          {saveSuccess && (
            <span className={styles.consentCookieSuccess} role="status">
              Kaydedildi.
            </span>
          )}
          {saveError && (
            <span className={styles.formError} role="alert">
              {saveError}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

// --- Delivery Health: big stat cards ---

function DeliveryHealthPanel({
  stats,
  loading,
  error,
  dateFrom,
  dateTo,
  activePreset,
  onSelectPreset,
}: {
  stats: TrackingStats | null;
  loading: boolean;
  error: string | null;
  dateFrom: string;
  dateTo: string;
  activePreset: PresetKey | null;
  onSelectPreset: (from: string, to: string) => void;
}) {
  return (
    <div className={styles.healthPanel}>
      <div className={styles.healthHeader}>
        <span className={styles.sectionTitleInline}>İletim Sağlığı</span>
        <DateRangePresets onSelect={onSelectPreset} activePreset={activePreset} />
        <span className={styles.dateRangeLabel}>
          {dateFrom} — {dateTo}
        </span>
      </div>

      {loading ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>İstatistikler yükleniyor...</span>
        </div>
      ) : error ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.errorText}>{error}</span>
        </div>
      ) : stats ? (
        <div className={styles.statCards}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>
              {stats.totals.total_events.toLocaleString('tr-TR')}
            </div>
            <div className={styles.statLabel}>Toplam Olay</div>
          </div>

          <div
            className={`${styles.statCard} ${
              stats.totals.total_errors > 0 ? styles.statCardError : ''
            }`}
          >
            <div
              className={`${styles.statValue} ${
                stats.totals.total_errors > 0 ? styles.statValueError : ''
              }`}
            >
              {stats.totals.total_errors.toLocaleString('tr-TR')}
            </div>
            <div className={styles.statLabel}>Hata</div>
          </div>

          <div className={styles.statCard}>
            <div className={styles.statValue}>
              {stats.totals.consent_blocked.toLocaleString('tr-TR')}
            </div>
            <div className={styles.statLabel}>Rıza ile Engellenen</div>
          </div>

          <div className={styles.statCardBreakdown}>
            <div className={styles.statLabel} style={{ marginBottom: '0.5rem' }}>
              Duruma Göre
            </div>
            {Object.entries(stats.totals.by_status).map(([status, count]) => (
              <div key={status} className={styles.byStatusRow}>
                <StatusBadge
                  status={RAW_STATUS_NORM[status] ?? 'received'}
                  label={RAW_STATUS_LABELS[status] ?? status}
                />
                <span className={styles.byStatusCount}>
                  {(count as number).toLocaleString('tr-TR')}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

// --- Inline bar sparkline for a single event row ---

function EventSparkline({ daily, eventName }: { daily: import('@/lib/tracking-api').DailyPoint[]; eventName: string }) {
  // Filter to last 14 points max for the sparkline, show only count
  const pts = daily.slice(-14).map((d) => ({
    date: fmtShortDate(d.date),
    count: d.count,
  }));

  if (pts.length === 0) return <span className={styles.muted}>—</span>;

  const maxCount = Math.max(...pts.map((p) => p.count), 1);

  return (
    <div
      className={styles.sparklineWrap}
      title={`${eventName} günlük trend`}
      aria-label={`${eventName} günlük trend`}
    >
      {pts.map((p, i) => {
        const h = Math.max(2, Math.round((p.count / maxCount) * 28));
        return (
          <div
            key={i}
            className={styles.sparkBar}
            style={{ height: `${h}px` }}
            title={`${p.date}: ${p.count}`}
          />
        );
      })}
    </div>
  );
}

// --- Event Distribution table (like SignalSight "Event Configuration") ---

function EventDistributionPanel({
  sourceId,
  stats,
  loading,
  error,
  onStatsRefetch,
}: {
  sourceId: string;
  stats: TrackingStats | null;
  loading: boolean;
  error: string | null;
  onStatsRefetch: () => void;
}) {
  // Optimistic enabled-state overlay: event_name → boolean.
  // When null the component reads directly from stats.by_event[].enabled.
  const [enabledOverrides, setEnabledOverrides] = useState<Record<string, boolean>>({});
  // Track which events are mid-toggle so we can disable the switch.
  const [togglingEvents, setTogglingEvents] = useState<Set<string>>(new Set());

  // When the source or stats change, clear stale overrides.
  useEffect(() => {
    setEnabledOverrides({});
  }, [sourceId]);

  async function handleToggle(ev: EventStat, newEnabled: boolean) {
    const name = ev.event_name;

    // Optimistic update
    setEnabledOverrides((prev) => ({ ...prev, [name]: newEnabled }));
    setTogglingEvents((prev) => new Set(prev).add(name));

    try {
      await toggleEventConfig(sourceId, name, newEnabled);
      // Refresh stats in background so the `enabled` field from the server
      // eventually reconciles with our optimistic state.
      onStatsRefetch();
    } catch {
      // Revert on error
      setEnabledOverrides((prev) => ({ ...prev, [name]: !newEnabled }));
    } finally {
      setTogglingEvents((prev) => {
        const next = new Set(prev);
        next.delete(name);
        return next;
      });
    }
  }

  const sorted = stats
    ? [...stats.by_event].sort((a, b) => b.count - a.count)
    : [];

  return (
    <div className={styles.sectionBlock}>
      <div className={styles.sectionTitle}>Olay Dağılımı</div>

      {loading ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>Yükleniyor...</span>
        </div>
      ) : error ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.errorText}>{error}</span>
        </div>
      ) : sorted.length === 0 ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>Bu dönemde olay verisi yok.</span>
        </div>
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
                  // Use optimistic override if present; fall back to what the
                  // backend told us (default true when field absent — old data).
                  const isEnabled =
                    ev.event_name in enabledOverrides
                      ? enabledOverrides[ev.event_name]
                      : (ev.enabled ?? true);
                  const isToggling = togglingEvents.has(ev.event_name);

                  return (
                    <tr
                      key={ev.event_name}
                      className={isEnabled ? undefined : styles.eventRowDisabled}
                    >
                      <td className={styles.eventNameCell}>{ev.event_name}</td>

                      {/* DURUM — toggle switch */}
                      <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <div className={styles.eventToggleCell}>
                          <button
                            role="switch"
                            aria-checked={isEnabled}
                            aria-label={
                              isEnabled
                                ? `${ev.event_name} olayını CAPI'ye göndermeyi durdur`
                                : `${ev.event_name} olayını CAPI'ye göndermeye başlat`
                            }
                            disabled={isToggling}
                            className={`${styles.eventToggleSwitch} ${
                              isEnabled ? styles.eventToggleSwitchOn : ''
                            } ${isToggling ? styles.eventToggleSwitchBusy : ''}`}
                            onClick={() => handleToggle(ev, !isEnabled)}
                          >
                            <span className={styles.eventToggleKnob} />
                          </button>
                          <span
                            className={
                              isEnabled
                                ? styles.eventToggleLabelOn
                                : styles.eventToggleLabelOff
                            }
                          >
                            {isEnabled ? 'Açık' : 'Kapalı'}
                          </span>
                        </div>
                      </td>

                      <td
                        style={{
                          textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums',
                          opacity: isEnabled ? 1 : 0.45,
                        }}
                      >
                        {ev.count.toLocaleString('tr-TR')}
                      </td>
                      <td
                        style={{
                          textAlign: 'right',
                          fontVariantNumeric: 'tabular-nums',
                          color: ev.errors > 0 ? 'var(--color-danger)' : undefined,
                          opacity: isEnabled ? 1 : 0.45,
                        }}
                      >
                        {ev.errors > 0 ? ev.errors.toLocaleString('tr-TR') : '—'}
                      </td>
                      <td style={{ opacity: isEnabled ? 1 : 0.35 }}>
                        <EventSparkline
                          daily={stats?.daily ?? []}
                          eventName={ev.event_name}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Daily events bar chart (aggregate) — matches SignalSight report bar chart */}
          {stats && stats.daily.length > 0 && (
            <div className={styles.dailyChartWrap}>
              <div className={styles.dailyChartTitle}>Günlük Olay Grafiği</div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart
                  data={stats.daily.map((d) => ({
                    date: fmtShortDate(d.date),
                    count: d.count,
                    errors: d.errors,
                  }))}
                  margin={{ top: 4, right: 12, left: 0, bottom: 0 }}
                  barCategoryGap="30%"
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                    tickLine={false}
                    axisLine={false}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                    tickLine={false}
                    axisLine={false}
                    width={36}
                    tickFormatter={(v: number) =>
                      v >= 1000 ? `${(v / 1000).toFixed(0)}K` : String(v)
                    }
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 8,
                      border: '1px solid var(--color-border)',
                      fontSize: 12,
                      background: 'var(--color-surface)',
                      color: 'var(--color-text)',
                    }}
                    formatter={(value: number, name: string) => [
                      value.toLocaleString('tr-TR'),
                      name === 'count' ? 'Olay' : 'Hata',
                    ]}
                    labelFormatter={(label: string) => `Tarih: ${label}`}
                  />
                  <Bar dataKey="count" fill="var(--color-primary)" radius={[3, 3, 0, 0]} name="count" />
                  <Bar dataKey="errors" fill="var(--color-danger)" radius={[3, 3, 0, 0]} name="errors" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// --- Destination config fields ---

interface DestCfgState {
  // meta_capi
  meta_pixel_id: string;
  meta_access_token: string;
  // tiktok_events
  tiktok_pixel_id: string;
  tiktok_access_token: string;
  // ga4_mp
  ga4_measurement_id: string;
  ga4_api_secret: string;
}

const DEFAULT_DEST_CFG: DestCfgState = {
  meta_pixel_id: '',
  meta_access_token: '',
  tiktok_pixel_id: '',
  tiktok_access_token: '',
  ga4_measurement_id: '',
  ga4_api_secret: '',
};

function buildDestConfig(
  platform: DestinationPlatform,
  cfg: DestCfgState,
): Record<string, string> {
  switch (platform) {
    case 'meta_capi':
      return { pixel_id: cfg.meta_pixel_id, access_token: cfg.meta_access_token };
    case 'tiktok_events':
      return { pixel_id: cfg.tiktok_pixel_id, access_token: cfg.tiktok_access_token };
    case 'ga4_mp':
      return {
        measurement_id: cfg.ga4_measurement_id,
        api_secret: cfg.ga4_api_secret,
      };
  }
}

function destConfigSummary(
  platform: DestinationPlatform,
  config: Record<string, string>,
): string {
  switch (platform) {
    case 'meta_capi':
      return `Pixel: ${config.pixel_id ?? '-'}`;
    case 'tiktok_events':
      return `Pixel: ${config.pixel_id ?? '-'}`;
    case 'ga4_mp':
      return `Measurement ID: ${config.measurement_id ?? '-'}`;
  }
}

// --- Destination add form ---

function DestinationForm({
  sourceId,
  onCreated,
  onCancel,
}: {
  sourceId: string;
  onCreated: () => void;
  onCancel: () => void;
}) {
  const [platform, setPlatform] = useState<DestinationPlatform>('meta_capi');
  const [cfg, setCfg] = useState<DestCfgState>({ ...DEFAULT_DEST_CFG });
  const [consentRequired, setConsentRequired] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  function updateCfg(key: keyof DestCfgState, value: string) {
    setCfg((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await createDestination(sourceId, {
        platform,
        config: buildDestConfig(platform, cfg),
        consent_required: consentRequired,
      });
      onCreated();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Hedef eklenemedi');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.destForm} onSubmit={handleSubmit}>
      <div className={styles.destFormTitle}>Yeni Hedef Ekle</div>

      <div className={styles.formRow}>
        <div className={styles.field}>
          <label className={styles.label}>Platform</label>
          <select
            className={styles.select}
            value={platform}
            onChange={(e) => {
              setPlatform(e.target.value as DestinationPlatform);
              setCfg({ ...DEFAULT_DEST_CFG });
            }}
            disabled={submitting}
          >
            {(Object.entries(PLATFORM_LABELS) as [DestinationPlatform, string][]).map(
              ([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ),
            )}
          </select>
        </div>
      </div>

      {platform === 'meta_capi' && (
        <div className={styles.formRow}>
          <div className={styles.field}>
            <label className={styles.label}>Pixel ID</label>
            <input
              className={styles.input}
              placeholder="123456789012345"
              value={cfg.meta_pixel_id}
              onChange={(e) => updateCfg('meta_pixel_id', e.target.value)}
              required
              disabled={submitting}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label}>Access Token</label>
            <input
              className={styles.input}
              type="password"
              placeholder="EAAxxxxxxx"
              value={cfg.meta_access_token}
              onChange={(e) => updateCfg('meta_access_token', e.target.value)}
              required
              disabled={submitting}
            />
          </div>
        </div>
      )}

      {platform === 'tiktok_events' && (
        <div className={styles.formRow}>
          <div className={styles.field}>
            <label className={styles.label}>Pixel ID</label>
            <input
              className={styles.input}
              placeholder="CXXXXXXXXXXXXXX"
              value={cfg.tiktok_pixel_id}
              onChange={(e) => updateCfg('tiktok_pixel_id', e.target.value)}
              required
              disabled={submitting}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label}>Access Token</label>
            <input
              className={styles.input}
              type="password"
              placeholder="TikTok Events API token"
              value={cfg.tiktok_access_token}
              onChange={(e) => updateCfg('tiktok_access_token', e.target.value)}
              required
              disabled={submitting}
            />
          </div>
        </div>
      )}

      {platform === 'ga4_mp' && (
        <div className={styles.formRow}>
          <div className={styles.field}>
            <label className={styles.label}>Measurement ID</label>
            <input
              className={styles.input}
              placeholder="G-XXXXXXXXXX"
              value={cfg.ga4_measurement_id}
              onChange={(e) => updateCfg('ga4_measurement_id', e.target.value)}
              required
              disabled={submitting}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label}>API Secret</label>
            <input
              className={styles.input}
              type="password"
              placeholder="GA4 Measurement Protocol API secret"
              value={cfg.ga4_api_secret}
              onChange={(e) => updateCfg('ga4_api_secret', e.target.value)}
              required
              disabled={submitting}
            />
          </div>
        </div>
      )}

      {/* KVKK consent toggle */}
      <div className={styles.consentRow}>
        <label
          className={styles.toggle}
          aria-label="KVKK rıza gerekli"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={consentRequired}
            onChange={(e) => setConsentRequired(e.target.checked)}
            disabled={submitting}
          />
          <span className={styles.toggleSlider} />
        </label>
        <div>
          <div className={styles.consentLabel}>KVKK rıza gerekli</div>
          <div className={styles.consentDesc}>
            Açık ise bu hedefe yalnızca rıza veren kullanıcı olayları iletilir.
          </div>
        </div>
      </div>

      {formError && <span className={styles.formError}>{formError}</span>}

      <div className={styles.formRow}>
        <button type="submit" className={styles.primaryBtn} disabled={submitting}>
          {submitting ? 'Ekleniyor...' : 'Hedef Ekle'}
        </button>
        <button
          type="button"
          className={styles.secondaryBtn}
          onClick={() => {
            onCancel();
          }}
          disabled={submitting}
        >
          Iptal
        </button>
      </div>
    </form>
  );
}

// --- Debug Console: filterable event log ---

function DebugConsole({
  sourceId,
  eventNames,
}: {
  sourceId: string;
  eventNames: string[];
}) {
  const [events, setEvents] = useState<TrackingEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState<EventStatus | ''>('');
  const [filterEvent, setFilterEvent] = useState('');

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getSourceEvents(sourceId, {
        status: filterStatus || undefined,
        event_name: filterEvent || undefined,
        limit: 200,
      });
      setEvents(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Olaylar yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, [sourceId, filterStatus, filterEvent]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  return (
    <div className={styles.sectionBlock}>
      <div className={styles.debugHeader}>
        <span className={styles.sectionTitleInline}>Olay Gunlugu</span>
        <div className={styles.debugFilters}>
          <select
            className={styles.selectSm}
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as EventStatus | '')}
            aria-label="Durum filtresi"
          >
            <option value="">Tüm Durumlar</option>
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>

          <select
            className={styles.selectSm}
            value={filterEvent}
            onChange={(e) => setFilterEvent(e.target.value)}
            aria-label="Olay filtresi"
          >
            <option value="">Tüm Olaylar</option>
            {eventNames.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>

          <button
            className={styles.secondaryBtn}
            onClick={fetchEvents}
            disabled={loading}
            aria-label="Yenile"
          >
            {loading ? '...' : 'Yenile'}
          </button>
        </div>
      </div>

      {loading ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>Olaylar yükleniyor...</span>
        </div>
      ) : error ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.errorText}>{error}</span>
          <br />
          <button
            className={styles.secondaryBtn}
            style={{ marginTop: '0.75rem' }}
            onClick={fetchEvents}
          >
            Tekrar Dene
          </button>
        </div>
      ) : events.length === 0 ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>
            {filterStatus || filterEvent
              ? 'Bu filtreyle esleyen olay bulunamadi.'
              : 'Henuz kayitli olay yok.'}
          </span>
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Olay Adi</th>
                <th>Zaman</th>
                <th>Durum</th>
                <th>İletim</th>
                <th>Hata Detayı</th>
              </tr>
            </thead>
            <tbody>
              {events.map((ev, idx) => (
                <tr key={ev.id ?? idx}>
                  <td>{ev.event_name}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(ev.event_time)}</td>
                  <td>
                    <StatusBadge status={ev.status} />
                  </td>
                  <td>{ev.forwarded_count}</td>
                  <td>
                    {ev.error_detail ? (
                      <span className={styles.errorDetail} title={ev.error_detail}>
                        {ev.error_detail.length > 60
                          ? ev.error_detail.slice(0, 60) + '...'
                          : ev.error_detail}
                      </span>
                    ) : (
                      <span className={styles.muted}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --- Source detail panel (right pane) ---

function SourceDetailPanel({
  source: initialSource,
  onSourceUpdated,
}: {
  source: TrackingSource;
  onSourceUpdated?: (updated: TrackingSource) => void;
}) {
  // Keep a local copy of the source so cookie consent saves update the view
  // without requiring a full refetch of the sources list.
  const [source, setSource] = useState<TrackingSource>(initialSource);
  useEffect(() => {
    setSource(initialSource);
  }, [initialSource]);

  // Snippet
  const [snippetInfo, setSnippetInfo] = useState<SnippetInfo | null>(null);
  const [snippetLoading, setSnippetLoading] = useState(true);
  const [snippetError, setSnippetError] = useState<string | null>(null);

  // Destinations
  const [destinations, setDestinations] = useState<TrackingDestination[]>([]);
  const [destLoading, setDestLoading] = useState(true);
  const [destError, setDestError] = useState<string | null>(null);
  const [showDestForm, setShowDestForm] = useState(false);
  const [deletingDestId, setDeletingDestId] = useState<string | null>(null);

  // Stats
  const [stats, setStats] = useState<TrackingStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);

  // Date range for stats (default: last 30 days)
  const defaultRange = computePreset('son30');
  const [statsDateFrom, setStatsDateFrom] = useState(defaultRange.from);
  const [statsDateTo, setStatsDateTo] = useState(defaultRange.to);

  const collectUrl = getCollectUrl(source.public_token);

  const fetchSnippet = useCallback(async () => {
    setSnippetLoading(true);
    setSnippetError(null);
    try {
      const data = await getSourceSnippet(source.id);
      setSnippetInfo(data);
    } catch (err: unknown) {
      setSnippetError(err instanceof Error ? err.message : 'Snippet yüklenemedi');
    } finally {
      setSnippetLoading(false);
    }
  }, [source.id]);

  // Called by CookieConsentCard after a successful save
  function handleSourceSaved(updated: TrackingSource) {
    setSource(updated);
    onSourceUpdated?.(updated);
    // Refetch snippet so it reflects the new consent variable
    fetchSnippet();
  }

  const fetchDestinations = useCallback(async () => {
    setDestLoading(true);
    setDestError(null);
    try {
      const data = await getSourceDestinations(source.id);
      setDestinations(data);
    } catch (err: unknown) {
      setDestError(err instanceof Error ? err.message : 'Hedefler yüklenemedi');
    } finally {
      setDestLoading(false);
    }
  }, [source.id]);

  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    setStatsError(null);
    try {
      const data = await getSourceStats(source.id, {
        date_from: statsDateFrom,
        date_to: statsDateTo,
      });
      setStats(data);
    } catch (err: unknown) {
      setStatsError(err instanceof Error ? err.message : 'İstatistikler yüklenemedi');
    } finally {
      setStatsLoading(false);
    }
  }, [source.id, statsDateFrom, statsDateTo]);

  useEffect(() => {
    fetchSnippet();
    fetchDestinations();
  }, [fetchSnippet, fetchDestinations]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  async function handleDeleteDest(id: string) {
    setDeletingDestId(id);
    try {
      await deleteDestination(id);
      await fetchDestinations();
    } catch {
      // non-fatal
    } finally {
      setDeletingDestId(null);
    }
  }

  function handleSelectPreset(from: string, to: string) {
    setStatsDateFrom(from);
    setStatsDateTo(to);
  }

  const activePreset = detectPreset(statsDateFrom, statsDateTo);
  // Event names from by_event for the debug console dropdown
  const eventNames = stats ? stats.by_event.map((e) => e.event_name) : [];

  return (
    <div className={styles.card}>
      <div className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>{source.name}</h2>
        <span className={styles.muted} style={{ fontSize: '0.8125rem' }}>
          {source.domain}
        </span>
      </div>

      {/* --- Collect URL --- */}
      <div className={styles.copyRow}>
        <span className={styles.copyRowLabel}>Collect URL</span>
        <span className={styles.copyRowValue} title={collectUrl}>
          {collectUrl}
        </span>
        <CopyButton text={collectUrl} />
      </div>

      {/* --- Embed Snippet --- */}
      <div className={styles.snippetBlock}>
        <div className={styles.snippetHeader}>
          <span className={styles.snippetLabel}>Entegrasyon Snippet</span>
          {snippetInfo ? (
            <SnippetCopyButton text={snippetInfo.snippet} />
          ) : null}
        </div>
        {snippetLoading ? (
          <code className={styles.snippetCode}>Yükleniyor...</code>
        ) : snippetError ? (
          <code className={styles.snippetCode} style={{ color: '#f87171' }}>
            {snippetError}
          </code>
        ) : snippetInfo ? (
          <code className={styles.snippetCode}>{snippetInfo.snippet}</code>
        ) : null}
      </div>

      {/* --- Çerez Rıza Değişkeni --- */}
      <CookieConsentCard source={source} onSaved={handleSourceSaved} />

      {/* --- Delivery Health panel --- */}
      <DeliveryHealthPanel
        stats={stats}
        loading={statsLoading}
        error={statsError}
        dateFrom={statsDateFrom}
        dateTo={statsDateTo}
        activePreset={activePreset}
        onSelectPreset={handleSelectPreset}
      />

      {/* --- Event Distribution table + bar chart --- */}
      <EventDistributionPanel
        sourceId={source.id}
        stats={stats}
        loading={statsLoading}
        error={statsError}
        onStatsRefetch={fetchStats}
      />

      {/* --- Destinations --- */}
      <div className={styles.sectionTitle}>Hedefler (Destinations)</div>

      {destLoading ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>Hedefler yükleniyor...</span>
        </div>
      ) : destError ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.errorText}>{destError}</span>
        </div>
      ) : destinations.length === 0 && !showDestForm ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>Henuz hedef eklenmedi.</span>
        </div>
      ) : (
        <div className={styles.destList}>
          {destinations.map((dest) => (
            <div key={dest.id} className={styles.destCard}>
              {/* Top row: platform badge + config summary + consent badge + delete */}
              <div className={styles.destRow}>
                <span className={styles.destPlatformBadge}>
                  {PLATFORM_LABELS[dest.platform] ?? dest.platform}
                </span>
                <span className={styles.destConfig}>
                  {destConfigSummary(dest.platform, dest.config)}
                </span>
                <span
                  className={`${styles.consentBadge} ${
                    dest.consent_required ? styles.consentOn : styles.consentOff
                  }`}
                >
                  {dest.consent_required ? 'KVKK rıza' : 'Rıza yok'}
                </span>
                <button
                  className={styles.dangerBtn}
                  disabled={deletingDestId === dest.id}
                  onClick={() => handleDeleteDest(dest.id)}
                >
                  {deletingDestId === dest.id ? '...' : 'Sil'}
                </button>
              </div>
              {/* Zorunlu Rıza Sinyalleri */}
              <DestConsentSignals
                dest={dest}
                onSaved={(updated) =>
                  setDestinations((prev) =>
                    prev.map((d) => (d.id === updated.id ? updated : d)),
                  )
                }
              />
            </div>
          ))}
        </div>
      )}

      {showDestForm ? (
        <DestinationForm
          sourceId={source.id}
          onCreated={() => {
            setShowDestForm(false);
            fetchDestinations();
          }}
          onCancel={() => setShowDestForm(false)}
        />
      ) : (
        <div className={styles.addBtnRow}>
          <button
            className={styles.secondaryBtn}
            onClick={() => setShowDestForm(true)}
          >
            + Hedef Ekle
          </button>
        </div>
      )}

      {/* --- Debug Console (filterable event log) --- */}
      <DebugConsole sourceId={source.id} eventNames={eventNames} />
    </div>
  );
}

// --- Main tracking page ---

export default function TrackingPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  const [sources, setSources] = useState<TrackingSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);

  // New source form
  const [showNewSource, setShowNewSource] = useState(false);
  const [nsName, setNsName] = useState('');
  const [nsDomain, setNsDomain] = useState('');
  const [nsSubmitting, setNsSubmitting] = useState(false);
  const [nsError, setNsError] = useState<string | null>(null);

  const fetchSources = useCallback(async () => {
    setSourcesLoading(true);
    setSourcesError(null);
    try {
      const data = await getTrackingSources();
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
      const created = await createTrackingSource({ name: nsName, domain: nsDomain });
      setSources((prev) => [...prev, created]);
      setSelectedSourceId(created.id);
      setNsName('');
      setNsDomain('');
      setShowNewSource(false);
    } catch (err: unknown) {
      setNsError(err instanceof Error ? err.message : 'Kaynak olusturulamadi');
    } finally {
      setNsSubmitting(false);
    }
  }

  const selectedSource = sources.find((s) => s.id === selectedSourceId) ?? null;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        <div>
          <h1 className={styles.pageTitle}>Olcumleme</h1>
          <p className={styles.pageSubtitle}>
            Sunucu tarafi izleme kaynaklarinizi yonetin, hedef platformlara olay iletin ve
            KVKK uyumlu riza akislarini yapilandirin.
          </p>
        </div>

        <div className={styles.layout}>
          {/* Left: source list */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>Izleme Kaynaklari</h2>
              {!showNewSource && (
                <button
                  className={styles.secondaryBtn}
                  onClick={() => setShowNewSource(true)}
                >
                  + Yeni Kaynak
                </button>
              )}
            </div>

            {showNewSource && (
              <form className={styles.formBox} onSubmit={handleCreateSource}>
                <div className={styles.field}>
                  <label className={styles.label}>Kaynak Adi</label>
                  <input
                    className={styles.input}
                    placeholder="Web Sitesi Ana"
                    value={nsName}
                    onChange={(e) => setNsName(e.target.value)}
                    required
                    disabled={nsSubmitting}
                  />
                </div>
                <div className={styles.field}>
                  <label className={styles.label}>Domain</label>
                  <input
                    className={styles.input}
                    placeholder="example.com"
                    value={nsDomain}
                    onChange={(e) => setNsDomain(e.target.value)}
                    required
                    disabled={nsSubmitting}
                  />
                </div>
                {nsError && <span className={styles.formError}>{nsError}</span>}
                <div className={styles.formRow}>
                  <button
                    type="submit"
                    className={styles.primaryBtn}
                    disabled={nsSubmitting}
                  >
                    {nsSubmitting ? 'Olusturuluyor...' : 'Olustur'}
                  </button>
                  <button
                    type="button"
                    className={styles.secondaryBtn}
                    onClick={() => {
                      setShowNewSource(false);
                      setNsError(null);
                    }}
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
                <button
                  className={styles.secondaryBtn}
                  style={{ marginTop: '0.75rem' }}
                  onClick={fetchSources}
                >
                  Tekrar Dene
                </button>
              </div>
            ) : sources.length === 0 ? (
              <div className={styles.stateBox}>
                <span className={styles.muted}>Henuz izleme kaynagi yok.</span>
              </div>
            ) : (
              <div className={styles.sourceList}>
                {sources.map((src) => (
                  <div
                    key={src.id}
                    className={`${styles.sourceItem} ${
                      selectedSourceId === src.id ? styles.sourceItemActive : ''
                    }`}
                    onClick={() => setSelectedSourceId(src.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) =>
                      e.key === 'Enter' && setSelectedSourceId(src.id)
                    }
                  >
                    <span
                      className={`${styles.sourceDot} ${
                        selectedSourceId === src.id ? styles.sourceDotActive : ''
                      }`}
                    />
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
                  <span className={styles.muted}>
                    {sourcesLoading
                      ? 'Yükleniyor...'
                      : 'Sol taraftan bir izleme kaynagi secin.'}
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
