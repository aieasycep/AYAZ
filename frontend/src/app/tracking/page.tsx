'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getTrackingSources,
  createTrackingSource,
  getSourceSnippet,
  getSourceEvents,
  getSourceDestinations,
  createDestination,
  deleteDestination,
  getCollectUrl,
  type TrackingSource,
  type TrackingDestination,
  type TrackingEvent,
  type DestinationPlatform,
  type EventStatus,
  type SnippetInfo,
} from '@/lib/tracking-api';
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

function StatusBadge({ status }: { status: EventStatus }) {
  const cls: Record<EventStatus, string> = {
    received: styles.statusReceived,
    forwarded: styles.statusForwarded,
    no_consent: styles.statusNoConsent,
    error: styles.statusError,
  };
  return (
    <span className={`${styles.statusBadge} ${cls[status] ?? ''}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
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
          İptal
        </button>
      </div>
    </form>
  );
}

// --- Source detail panel (right pane) ---

function SourceDetailPanel({ source }: { source: TrackingSource }) {
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

  // Events
  const [events, setEvents] = useState<TrackingEvent[]>([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState<string | null>(null);

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

  const fetchEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const data = await getSourceEvents(source.id);
      setEvents(data);
    } catch (err: unknown) {
      setEventsError(err instanceof Error ? err.message : 'Olaylar yüklenemedi');
    } finally {
      setEventsLoading(false);
    }
  }, [source.id]);

  useEffect(() => {
    fetchSnippet();
    fetchDestinations();
    fetchEvents();
  }, [fetchSnippet, fetchDestinations, fetchEvents]);

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
          <span className={styles.muted}>Henüz hedef eklenmedi.</span>
        </div>
      ) : (
        <div className={styles.destList}>
          {destinations.map((dest) => (
            <div key={dest.id} className={styles.destRow}>
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

      {/* --- Event log --- */}
      <div className={styles.sectionTitle}>Olay Günlüğü</div>

      {eventsLoading ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>Olaylar yükleniyor...</span>
        </div>
      ) : eventsError ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.errorText}>{eventsError}</span>
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
          <span className={styles.muted}>Henüz kayıtlı olay yok.</span>
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Olay Adı</th>
                <th>Zaman</th>
                <th>Durum</th>
                <th>İletim</th>
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
      setNsError(err instanceof Error ? err.message : 'Kaynak oluşturulamadı');
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
          <h1 className={styles.pageTitle}>Ölçümleme</h1>
          <p className={styles.pageSubtitle}>
            Sunucu tarafı izleme kaynaklarınızı yönetin, hedef platformlara olay iletin ve
            KVKK uyumlu rıza akışlarını yapılandırın.
          </p>
        </div>

        <div className={styles.layout}>
          {/* Left: source list */}
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <h2 className={styles.cardTitle}>İzleme Kaynakları</h2>
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
                  <label className={styles.label}>Kaynak Adı</label>
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
                    {nsSubmitting ? 'Oluşturuluyor...' : 'Oluştur'}
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
                <span className={styles.muted}>Henüz izleme kaynağı yok.</span>
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
                      : 'Sol taraftan bir izleme kaynağı seçin.'}
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
