// Ads API — typed wrappers for /api/v1/ads/*

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

export type CampaignStatus = 'active' | 'paused' | 'ended' | 'draft';

export interface Campaign {
  campaign_id: string;
  campaign_name: string;
  channel: string;
  status: CampaignStatus;
  spend: number;
  impressions: number;
  clicks: number;
  conversions: number;
  conversion_value: number;
  ctr: number;
  cpc: number;
  cpa: number;
  roas: number;
}

export interface CampaignTimeseriesPoint {
  date: string;
  value: number;
}

export interface CampaignDetail {
  totals: Campaign;
  timeseries: CampaignTimeseriesPoint[];
}

export type RecommendationSeverity = 'critical' | 'warning' | 'info';

export interface Recommendation {
  campaign_id: string;
  campaign_name: string;
  severity: RecommendationSeverity;
  message: string;
  suggested_action: string;
}

export type CampaignSortField =
  | 'spend'
  | 'roas'
  | 'cpc'
  | 'ctr'
  | 'conversions'
  | 'impressions'
  | 'clicks';

export interface GetCampaignsParams {
  date_from?: string;
  date_to?: string;
  channel?: string;
  status?: CampaignStatus | '';
  sort?: CampaignSortField;
}

// --- API functions ---

export function getCampaigns(params?: GetCampaignsParams): Promise<Campaign[]> {
  const qs = new URLSearchParams();
  if (params?.date_from) qs.set('date_from', params.date_from);
  if (params?.date_to) qs.set('date_to', params.date_to);
  if (params?.channel) qs.set('channel', params.channel);
  if (params?.status) qs.set('status', params.status);
  if (params?.sort) qs.set('sort', params.sort);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return authFetch<Campaign[]>(`/api/v1/ads/campaigns${query}`);
}

export async function getCampaignDetail(
  id: string,
  date_from: string,
  date_to: string,
): Promise<CampaignDetail> {
  const qs = new URLSearchParams({ date_from, date_to });
  // Backend timeseries rows are {date, spend, impressions, ...}; the chart needs {date, value}.
  const raw = await authFetch<{
    totals: Campaign;
    timeseries: Array<Record<string, unknown>>;
  }>(`/api/v1/ads/campaigns/${id}?${qs}`);
  return {
    totals: raw.totals,
    timeseries: (raw.timeseries ?? []).map((p) => ({
      date: String(p.date),
      value: Number((p.spend ?? p.value ?? 0) as number),
    })),
  };
}

export function getRecommendations(params?: {
  date_from?: string;
  date_to?: string;
}): Promise<Recommendation[]> {
  const qs = new URLSearchParams();
  if (params?.date_from) qs.set('date_from', params.date_from);
  if (params?.date_to) qs.set('date_to', params.date_to);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return authFetch<Recommendation[]>(`/api/v1/ads/recommendations${query}`);
}
