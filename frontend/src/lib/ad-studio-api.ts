// Ad Studio API — typed wrappers for /api/v1/ad-studio/*

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

  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type AdPlatform = 'google_ads' | 'meta_ads' | 'tiktok_ads';
export type AdTone = 'profesyonel' | 'samimi' | 'heyecanli' | 'bilgilendirici';
export type DraftStatus = 'saved' | 'archived';

export const PLATFORM_LABELS: Record<AdPlatform, string> = {
  google_ads: 'Google Ads',
  meta_ads: 'Meta (Facebook/Instagram)',
  tiktok_ads: 'TikTok',
};

export const TONE_LABELS: Record<AdTone, string> = {
  profesyonel: 'Profesyonel',
  samimi: 'Samimi',
  heyecanli: 'Heyecanlı',
  bilgilendirici: 'Bilgilendirici',
};

export interface AdField {
  key: string;
  label: string;
  value: string;
  char_count: number;
  max_len: number;
  within_limit: boolean;
}

export interface AdVariant {
  index: number;
  fields: AdField[];
}

export interface AdGenerateRequest {
  platform: AdPlatform;
  product: string;
  value_prop?: string;
  tone?: AdTone;
  keywords?: string[];
  audience?: string;
  n_variants?: number;
}

export interface AdGenerateResult {
  platform: AdPlatform;
  platform_label: string;
  source: 'ai' | 'template';
  tone: AdTone;
  tone_label: string;
  variants: AdVariant[];
}

export interface AdCopyDraft {
  id: string;
  platform: AdPlatform;
  platform_label: string;
  title: string;
  brief: AdGenerateRequest;
  variants: AdVariant[];
  source: 'ai' | 'template';
  status: DraftStatus;
  created_at: string;
  updated_at: string;
}

// --- API functions ---

export function generateAdCopy(req: AdGenerateRequest): Promise<AdGenerateResult> {
  return authFetch<AdGenerateResult>('/api/v1/ad-studio/generate', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export interface SaveDraftPayload {
  platform: AdPlatform;
  title: string;
  brief: AdGenerateRequest;
  variants: AdVariant[];
  source?: 'ai' | 'template';
}

export function saveDraft(payload: SaveDraftPayload): Promise<AdCopyDraft> {
  return authFetch<AdCopyDraft>('/api/v1/ad-studio/drafts', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listDrafts(status?: DraftStatus): Promise<AdCopyDraft[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : '';
  return authFetch<AdCopyDraft[]>(`/api/v1/ad-studio/drafts${qs}`);
}

export function updateDraftStatus(id: string, status: DraftStatus): Promise<AdCopyDraft> {
  return authFetch<AdCopyDraft>(`/api/v1/ad-studio/drafts/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

export function deleteDraft(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/ad-studio/drafts/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}
