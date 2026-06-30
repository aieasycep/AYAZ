// Creatives API — typed wrappers for /api/v1/creatives/*

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

  return res.json() as Promise<T>;
}

// --- Types ---

export interface AdPerformance {
  ad_id: string;
  ad_name: string;
  campaign_name: string;
  channel: string;
  spend: number;
  impressions: number;
  clicks: number;
  conversions: number;
  roas: number;
  ctr: number;
  cpc: number;
}

export interface CreativesPerformanceResponse {
  ads: AdPerformance[];
  top: AdPerformance[];
  bottom: AdPerformance[];
  commentary: string;
}

export type AdSortField =
  | 'spend'
  | 'roas'
  | 'ctr'
  | 'conversions'
  | 'impressions'
  | 'clicks'
  | 'cpc';

export interface GetCreativesParams {
  date_from?: string;
  date_to?: string;
  sort?: AdSortField;
}

// --- API functions ---

export function getCreativesPerformance(
  params?: GetCreativesParams,
): Promise<CreativesPerformanceResponse> {
  const qs = new URLSearchParams();
  if (params?.date_from) qs.set('date_from', params.date_from);
  if (params?.date_to) qs.set('date_to', params.date_to);
  if (params?.sort) qs.set('sort', params.sort);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return authFetch<CreativesPerformanceResponse>(
    `/api/v1/creatives/performance${query}`,
  );
}
