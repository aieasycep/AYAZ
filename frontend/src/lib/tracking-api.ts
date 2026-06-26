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
}

export interface SnippetInfo {
  collect_url: string;
  snippet: string;
}

export interface TrackingDestination {
  id: string;
  source_id: string;
  platform: DestinationPlatform;
  config: Record<string, string>;
  consent_required: boolean;
  is_active: boolean;
  created_at: string;
}

export interface TrackingEvent {
  id?: string;
  event_name: string;
  event_time: string; // ISO
  status: EventStatus;
  forwarded_count: number;
  destination_platform?: DestinationPlatform | null;
  error_detail?: string | null;
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

export function getSourceSnippet(sourceId: string): Promise<SnippetInfo> {
  return authFetch<SnippetInfo>(`/api/v1/tracking/sources/${sourceId}/snippet`);
}

// --- Events ---

export function getSourceEvents(sourceId: string): Promise<TrackingEvent[]> {
  return authFetch<TrackingEvent[]>(`/api/v1/tracking/sources/${sourceId}/events`);
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
