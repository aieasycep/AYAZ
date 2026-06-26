// Feeds API — typed wrappers for /api/v1/feeds/*

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

  return res.json() as Promise<T>;
}

// --- Types ---

export type SourceType = 'url_xml' | 'url_csv' | 'upload';

export type ChannelType =
  | 'google_shopping'
  | 'meta_catalog'
  | 'tiktok'
  | 'custom';

export type OutputFormat = 'xml' | 'csv' | 'json' | 'tsv';

export type RuleType =
  | 'set_value'
  | 'rename_field'
  | 'find_replace'
  | 'filter_include'
  | 'filter_exclude'
  | 'calculated';

export interface FeedSource {
  id: string;
  name: string;
  source_type: SourceType;
  source_url: string | null;
  item_count: number | null;
  last_synced: string | null; // ISO date — normalised from backend `last_synced_at`
  created_at: string;
}

export interface FeedChannel {
  id: string;
  // Backend field is `feed_source_id`; kept here for the FK. The list page does
  // not dereference this, so the rename is non-breaking.
  feed_source_id: string;
  name: string;
  channel_type: ChannelType;
  output_format: OutputFormat;
  public_token: string;
  is_active: boolean;
  created_at: string;
}

export interface FeedRule {
  id: string;
  channel_id: string;
  position: number;
  rule_type: RuleType;
  config: Record<string, unknown>;
  created_at: string;
}

// --- Normalisation ---
// Backend returns `last_synced_at`; the UI reads `last_synced`. Map it here.
function normaliseFeedSource(
  s: FeedSource & { last_synced_at?: string | null },
): FeedSource {
  if (s && s.last_synced == null && s.last_synced_at !== undefined) {
    s.last_synced = s.last_synced_at;
  }
  return s;
}

// --- Source API ---

export async function getFeedSources(): Promise<FeedSource[]> {
  const sources = await authFetch<FeedSource[]>('/api/v1/feeds/sources');
  return sources.map(normaliseFeedSource);
}

export interface CreateSourcePayload {
  name: string;
  source_type: SourceType;
  source_url: string;
}

export async function createFeedSource(
  payload: CreateSourcePayload,
): Promise<FeedSource> {
  return normaliseFeedSource(
    await authFetch<FeedSource>('/api/v1/feeds/sources', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  );
}

export async function syncFeedSource(id: string): Promise<FeedSource> {
  return normaliseFeedSource(
    await authFetch<FeedSource>(`/api/v1/feeds/sources/${id}/sync`, {
      method: 'POST',
    }),
  );
}

// --- Channel API ---

export function getFeedChannels(sourceId: string): Promise<FeedChannel[]> {
  return authFetch<FeedChannel[]>(`/api/v1/feeds/sources/${sourceId}/channels`);
}

export interface CreateChannelPayload {
  name: string;
  channel_type: ChannelType;
  output_format: OutputFormat;
}

export function createFeedChannel(
  sourceId: string,
  payload: CreateChannelPayload,
): Promise<FeedChannel> {
  return authFetch<FeedChannel>(`/api/v1/feeds/sources/${sourceId}/channels`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// --- Rule API ---

export function getChannelRules(channelId: string): Promise<FeedRule[]> {
  return authFetch<FeedRule[]>(`/api/v1/feeds/channels/${channelId}/rules`);
}

export interface CreateRulePayload {
  position: number;
  rule_type: RuleType;
  config: Record<string, unknown>;
}

export function createChannelRule(
  channelId: string,
  payload: CreateRulePayload,
): Promise<FeedRule> {
  return authFetch<FeedRule>(`/api/v1/feeds/channels/${channelId}/rules`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// --- Public feed URL helper ---

export function getPublicFeedUrl(publicToken: string): string {
  return `${API_BASE}/api/v1/feeds/public/${publicToken}`;
}
