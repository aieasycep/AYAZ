// Marcom (Marketing Creative Lens) API — typed wrappers for /api/v1/marcom/*

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

export interface LensTotals {
  impressions: number;
  clicks: number;
  /** CTR as a percent value, e.g. 3.1 means 3.1% */
  ctr: number;
  conversions: number;
  creatives_count: number;
}

export interface CreativeRow {
  ad_id: string;
  ad_name: string;
  campaign_name: string;
  channel: string;
  impressions: number;
  clicks: number;
  /** CTR as a percent value, e.g. 3.1 means 3.1% */
  ctr: number;
  conversions: number;
  traffic_share_pct: number;
  insight: string;
}

export interface CreativeLens {
  period: {
    date_from: string;
    date_to: string;
  };
  totals: LensTotals;
  headline: string;
  top_creatives: CreativeRow[];
}

// --- API functions ---

export interface GetCreativeInsightsOptions {
  date_from?: string;
  date_to?: string;
}

export function getCreativeInsights(
  opts: GetCreativeInsightsOptions = {},
): Promise<CreativeLens> {
  const params = new URLSearchParams();
  if (opts.date_from) params.set('date_from', opts.date_from);
  if (opts.date_to) params.set('date_to', opts.date_to);
  const qs = params.toString();
  return authFetch<CreativeLens>(
    `/api/v1/marcom/creative-insights${qs ? `?${qs}` : ''}`,
  );
}
