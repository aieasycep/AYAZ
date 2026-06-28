// Tracking (Server-side / CAPI) API — typed wrappers for /api/v1/tracking/*

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

const TOKEN_KEY = 'ayaz_token';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

async function authFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const url = `${API_BASE}${path}`;

  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token ?? ''}`,
      ...options?.headers,
    },
  });

  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = '/login';
    }
    throw new Error('Oturum süresi doldu');
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => 'İstek başarısız');
    throw new Error(detail || 'İstek başarısız');
  }

  // DELETE / 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type DestinationPlatform = 'meta_capi' | 'tiktok_events' | 'ga4_mp';

export type EventStatus = 'received' | 'forwarded' | 'no_consent' | 'error';

export interface TrackingSource {
  id: string;
  name: string;
  domain: string;
  public_token: string;
  created_at: string;
  consent_cookie_var: string | null;
}

// Consent Mode v2 signal keys
export type ConsentSignal =
  | 'ad_storage'
  | 'ad_user_data'
  | 'ad_personalization'
  | 'analytics_storage';

export const CONSENT_SIGNAL_LABELS: Record<ConsentSignal, string> = {
  ad_storage: 'Reklam Depolama',
  ad_user_data: 'Reklam Kullanıcı Verisi',
  ad_personalization: 'Reklam Kişiselleştirme',
  analytics_storage: 'Analitik Depolama',
};

// All four signals in display order
export const ALL_CONSENT_SIGNALS: ConsentSignal[] = [
  'ad_storage',
  'ad_user_data',
  'ad_personalization',
  'analytics_storage',
];

// Platform defaults when required_consent is null/empty
export const PLATFORM_DEFAULT_CONSENT: Record<string, ConsentSignal[]> = {
  meta_capi: ['ad_user_data'],
  tiktok_events: ['ad_user_data'],
  ga4_mp: ['analytics_storage'],
};

export interface SnippetInfo {
  collect_url: string;
  snippet: string;
}

export interface TrackingDestination {
  id: string;
  // Backend field is `tracking_source_id`; the list page does not dereference it.
  tracking_source_id: string;
  platform: DestinationPlatform;
  config: Record<string, string>;
  consent_required: boolean;
  is_active: boolean;
  created_at: string;
  required_consent: ConsentSignal[] | null;
}

export interface TrackingEvent {
  id?: string;
  event_name: string;
  event_time: string; // ISO
  status: EventStatus;
  forwarded_count: number;
  destination_platform?: DestinationPlatform | null;
  error_detail?: string | null;
  match_quality?: { score: number; tier: string; present: string[] } | null;
}

// --- Source API ---

export function getTrackingSources(): Promise<TrackingSource[]> {
  return authFetch<TrackingSource[]>('/api/v1/tracking/sources');
}

export interface CreateTrackingSourcePayload {
  name: string;
  domain: string;
}

export function createTrackingSource(
  payload: CreateTrackingSourcePayload,
): Promise<TrackingSource> {
  return authFetch<TrackingSource>('/api/v1/tracking/sources', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getTrackingSource(id: string): Promise<TrackingSource> {
  return authFetch<TrackingSource>(`/api/v1/tracking/sources/${id}`);
}

export interface UpdateTrackingSourcePayload {
  name?: string;
  domain?: string;
  consent_cookie_var?: string | null;
}

export function patchTrackingSource(
  id: string,
  payload: UpdateTrackingSourcePayload,
): Promise<TrackingSource> {
  return authFetch<TrackingSource>(`/api/v1/tracking/sources/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteTrackingSource(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/tracking/sources/${id}`, {
    method: 'DELETE',
  });
}

// --- Snippet ---

// Backend returns {collect_url, js_snippet}; the UI reads {collect_url, snippet}.
export async function getSourceSnippet(sourceId: string): Promise<SnippetInfo> {
  const raw = await authFetch<SnippetInfo & { js_snippet?: string }>(
    `/api/v1/tracking/sources/${sourceId}/snippet`,
  );
  return {
    collect_url: raw.collect_url,
    snippet: raw.snippet ?? raw.js_snippet ?? '',
  };
}

// --- Stats types ---

export interface EventStat {
  event_name: string;
  count: number;
  errors: number;
  /**
   * False when the event is disabled in event-config and not forwarded to CAPI.
   * Absent on old backend responses — treat missing as true (enabled).
   */
  enabled?: boolean;
}

// --- Event config ---

export interface EventConfigResponse {
  disabled_events: string[];
}

/**
 * Enable or disable forwarding of a specific event name to CAPI.
 * POST /api/v1/tracking/sources/{source_id}/event-config
 */
export function toggleEventConfig(
  sourceId: string,
  eventName: string,
  enabled: boolean,
): Promise<EventConfigResponse> {
  return authFetch<EventConfigResponse>(
    `/api/v1/tracking/sources/${sourceId}/event-config`,
    {
      method: 'POST',
      body: JSON.stringify({ event_name: eventName, enabled }),
    },
  );
}

export interface DailyPoint {
  date: string; // YYYY-MM-DD
  count: number;
  errors: number;
}

// --- Match Quality (Event Match Quality / EMQ-style) ---

// Canonical identity-signal key tier (matches backend tier labels).
export type MatchTier = 'weak' | 'medium' | 'good' | 'excellent';

export interface MatchQualityFieldStat {
  key: string; // em | ph | fbc | fbp | external_id | client_ip_address | ...
  weight: number;
  present: number;
  coverage_pct: number;
}

export interface MatchQualityStats {
  avg_score: number; // 0-100
  scored_events: number;
  tier_distribution: Record<string, number>; // weak|medium|good|excellent → count
  field_coverage: MatchQualityFieldStat[];
}

// Turkish display label for each canonical match-quality signal key.
export const MATCH_FIELD_LABELS: Record<string, string> = {
  em: 'E-posta',
  ph: 'Telefon',
  fbc: 'Tıklama Kimliği (fbc)',
  fbp: 'Tarayıcı Kimliği (fbp)',
  external_id: 'Harici Kimlik',
  client_ip_address: 'IP Adresi',
  client_user_agent: 'Tarayıcı Bilgisi',
  fn: 'Ad',
  ln: 'Soyad',
  zp: 'Posta Kodu',
  ct: 'Şehir',
  st: 'İl / Bölge',
  country: 'Ülke',
  ge: 'Cinsiyet',
};

// Tier → Turkish label + colour bucket.
export const MATCH_TIER_LABELS: Record<string, string> = {
  weak: 'Zayıf',
  medium: 'Orta',
  good: 'İyi',
  excellent: 'Mükemmel',
};

// Tier display order (worst → best).
export const MATCH_TIER_ORDER: MatchTier[] = [
  'weak',
  'medium',
  'good',
  'excellent',
];

export interface TrackingStats {
  source_id: string;
  date_from: string;
  date_to: string;
  totals: {
    total_events: number;
    total_errors: number;
    by_status: Record<string, number>;
    consent_blocked: number;
  };
  by_event: EventStat[];
  daily: DailyPoint[];
  match_quality?: MatchQualityStats | null;
}

export interface GetSourceStatsOptions {
  date_from?: string;
  date_to?: string;
}

export function getSourceStats(
  sourceId: string,
  options: GetSourceStatsOptions = {},
): Promise<TrackingStats> {
  const params = new URLSearchParams();
  if (options.date_from) params.set('date_from', options.date_from);
  if (options.date_to) params.set('date_to', options.date_to);
  const qs = params.toString();
  return authFetch<TrackingStats>(
    `/api/v1/tracking/sources/${sourceId}/stats${qs ? `?${qs}` : ''}`,
  );
}

// --- Events ---

// Backend stores statuses {received, forwarded, duplicate, skipped_no_consent,
// failed}; the UI vocabulary is {received, forwarded, no_consent, error}.
const EVENT_STATUS_MAP: Record<string, EventStatus> = {
  received: 'received',
  forwarded: 'forwarded',
  no_consent: 'no_consent',
  skipped_no_consent: 'no_consent',
  error: 'error',
  failed: 'error',
};

function normaliseEvent(e: TrackingEvent): TrackingEvent {
  if (e && e.status) {
    e.status = EVENT_STATUS_MAP[e.status as string] ?? e.status;
  }
  return e;
}

export interface GetSourceEventsOptions {
  status?: EventStatus;
  event_name?: string;
  limit?: number;
}

export async function getSourceEvents(
  sourceId: string,
  options: GetSourceEventsOptions = {},
): Promise<TrackingEvent[]> {
  const params = new URLSearchParams();
  if (options.status) params.set('status', options.status);
  if (options.event_name) params.set('event_name', options.event_name);
  if (options.limit !== undefined) params.set('limit', String(options.limit));
  const qs = params.toString();
  const events = await authFetch<TrackingEvent[]>(
    `/api/v1/tracking/sources/${sourceId}/events${qs ? `?${qs}` : ''}`,
  );
  return events.map(normaliseEvent);
}

// --- Destinations ---

export function getSourceDestinations(sourceId: string): Promise<TrackingDestination[]> {
  return authFetch<TrackingDestination[]>(
    `/api/v1/tracking/sources/${sourceId}/destinations`,
  );
}

export interface CreateDestinationPayload {
  platform: DestinationPlatform;
  config: Record<string, string>;
  consent_required: boolean;
}

export function createDestination(
  sourceId: string,
  payload: CreateDestinationPayload,
): Promise<TrackingDestination> {
  return authFetch<TrackingDestination>(
    `/api/v1/tracking/sources/${sourceId}/destinations`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  );
}

export interface UpdateDestinationPayload {
  config?: Record<string, string>;
  consent_required?: boolean;
  is_active?: boolean;
  required_consent?: ConsentSignal[] | null;
}

export function patchDestination(
  id: string,
  payload: UpdateDestinationPayload,
): Promise<TrackingDestination> {
  return authFetch<TrackingDestination>(`/api/v1/tracking/destinations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteDestination(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/tracking/destinations/${id}`, {
    method: 'DELETE',
  });
}

// --- Public collect URL helper ---

export function getCollectUrl(publicToken: string): string {
  return `${API_BASE}/api/v1/tracking/collect/${publicToken}`;
}
