// Content Planner API — typed wrappers for /api/v1/content/*

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
    // Attach the HTTP status so callers (parseApiError) can distinguish
    // server errors (5xx) from client errors (4xx) without string-matching.
    const err = new Error(detail || 'İstek başarısız') as Error & { status?: number };
    err.status = res.status;
    throw err;
  }

  // DELETE / 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type Channel =
  | 'instagram'
  | 'facebook'
  | 'x'
  | 'linkedin'
  | 'tiktok'
  | 'youtube';

export type ContentStatus =
  | 'draft'
  | 'pending_approval'
  | 'approved'
  | 'scheduled'
  | 'published'
  | 'archived';

export interface ContentPost {
  id: string;
  tenant_id: string;
  title: string;
  body: string | null;
  channels: Channel[];
  scheduled_at: string | null;
  status: ContentStatus;
  approval_note: string | null;
  media_url: string | null;
  ai_assisted: boolean;
  created_at: string;
  updated_at: string;
}

// --- Label maps ---

export const CHANNEL_LABELS: Record<Channel, string> = {
  instagram: 'Instagram',
  facebook: 'Facebook',
  x: 'X (Twitter)',
  linkedin: 'LinkedIn',
  tiktok: 'TikTok',
  youtube: 'YouTube',
};

export const ALL_CHANNELS: Channel[] = [
  'instagram',
  'facebook',
  'x',
  'linkedin',
  'tiktok',
  'youtube',
];

export const STATUS_LABELS: Record<ContentStatus, string> = {
  draft: 'Taslak',
  pending_approval: 'Onay Bekliyor',
  approved: 'Onaylandı',
  scheduled: 'Zamanlandı',
  published: 'Yayınlandı',
  archived: 'Arşiv',
};

// Columns shown on the kanban board (archived excluded from board)
export const STATUS_ORDER: ContentStatus[] = [
  'draft',
  'pending_approval',
  'approved',
  'scheduled',
  'published',
];

// --- API functions ---

export interface GetContentPostsOptions {
  status?: ContentStatus;
  channel?: Channel;
  date_from?: string;
  date_to?: string;
}

export function getContentPosts(
  options: GetContentPostsOptions = {},
): Promise<ContentPost[]> {
  const params = new URLSearchParams();
  if (options.status) params.set('status', options.status);
  if (options.channel) params.set('channel', options.channel);
  if (options.date_from) params.set('date_from', options.date_from);
  if (options.date_to) params.set('date_to', options.date_to);
  const qs = params.toString();
  return authFetch<ContentPost[]>(
    `/api/v1/content/posts${qs ? `?${qs}` : ''}`,
  );
}

export interface CreateContentPostPayload {
  title: string;
  body?: string;
  channels?: Channel[];
  scheduled_at?: string | null;
  media_url?: string | null;
}

export function createContentPost(
  payload: CreateContentPostPayload,
): Promise<ContentPost> {
  return authFetch<ContentPost>('/api/v1/content/posts', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getContentPost(id: string): Promise<ContentPost> {
  return authFetch<ContentPost>(`/api/v1/content/posts/${id}`);
}

export interface PatchContentPostPayload {
  title?: string;
  body?: string;
  channels?: Channel[];
  scheduled_at?: string | null;
  media_url?: string | null;
  status?: ContentStatus;
}

export function patchContentPost(
  id: string,
  payload: PatchContentPostPayload,
): Promise<ContentPost> {
  return authFetch<ContentPost>(`/api/v1/content/posts/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteContentPost(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/content/posts/${id}`, {
    method: 'DELETE',
  });
}

export function submitPost(id: string): Promise<ContentPost> {
  return authFetch<ContentPost>(`/api/v1/content/posts/${id}/submit`, {
    method: 'POST',
  });
}

export function approvePost(id: string): Promise<ContentPost> {
  return authFetch<ContentPost>(`/api/v1/content/posts/${id}/approve`, {
    method: 'POST',
  });
}

export function rejectPost(id: string, note?: string): Promise<ContentPost> {
  return authFetch<ContentPost>(`/api/v1/content/posts/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify(note ? { note } : {}),
  });
}

export function schedulePost(
  id: string,
  scheduledAt: string,
): Promise<ContentPost> {
  return authFetch<ContentPost>(`/api/v1/content/posts/${id}/schedule`, {
    method: 'POST',
    body: JSON.stringify({ scheduled_at: scheduledAt }),
  });
}

// publishPost always returns {gated: true, message} on a 501 from the backend
// instead of throwing, so the UI can surface a friendly note.
export interface PublishGatedResult {
  gated: true;
  message: string;
}

export async function publishPost(
  id: string,
): Promise<ContentPost | PublishGatedResult> {
  const token = getToken();
  const url = `${API_BASE}/api/v1/content/posts/${id}/publish`;

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token ?? ''}`,
    },
  });

  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = '/login';
    }
    throw new Error('Oturum süresi doldu');
  }

  // Credential gate — 501 means the channel credentials are not connected
  if (res.status === 501) {
    return {
      gated: true,
      message:
        'Yayınlama için kanal kimlik bilgileri (OAuth) gereklidir. Lütfen Ayarlar bölümünden kanalınızı bağlayın.',
    };
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => 'İstek başarısız');
    // Attach the HTTP status so callers (parseApiError) can distinguish
    // server errors (5xx) from client errors (4xx) without string-matching.
    const err = new Error(detail || 'İstek başarısız') as Error & { status?: number };
    err.status = res.status;
    throw err;
  }

  return res.json() as Promise<ContentPost>;
}

// --- AI Caption ---

export interface GenerateCaptionPayload {
  brief: string;
  channel?: Channel;
  tone?: string;
}

export interface GenerateCaptionResult {
  caption: string;
  hashtags: string[];
  ai_assisted: boolean;
}

export function generateCaption(
  payload: GenerateCaptionPayload,
): Promise<GenerateCaptionResult> {
  return authFetch<GenerateCaptionResult>('/api/v1/content/ai-caption', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// --- Kreatif → İçerik köprüsü (turn a top ad creative into a draft) ---

export interface CreateFromCreativePayload {
  ad_name: string;
  campaign_name?: string;
  channel?: string; // ad platform label (meta, google, tiktok, ...)
  media_url?: string;
  tone?: string;
}

/**
 * Create an organic content draft from a high-performing ad creative.
 * The ad's theme is adapted into an organic caption and the ad platform is
 * mapped to the matching social channels. Returns a new draft ContentPost.
 */
export function createFromCreative(
  payload: CreateFromCreativePayload,
): Promise<ContentPost> {
  return authFetch<ContentPost>('/api/v1/content/from-creative', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
