const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

// --- Auth ---

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => 'Giriş başarısız');
    throw new Error(detail || 'Giriş başarısız');
  }

  return res.json() as Promise<LoginResponse>;
}

// --- Token helpers ---

const TOKEN_KEY = 'ayaz_token';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
}

// --- Authenticated fetch ---

async function authFetch<T>(path: string, params?: Record<string, string>): Promise<T> {
  const token = getToken();
  const url = new URL(`${API_BASE}${path}`);

  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }

  const res = await fetch(url.toString(), {
    headers: {
      Authorization: `Bearer ${token ?? ''}`,
    },
  });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== 'undefined') {
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

// --- Dashboard ---

export interface Totals {
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

export interface ChannelRow {
  channel: string;
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

export interface DashboardSummary {
  date_from: string;
  date_to: string;
  totals: Totals;
  by_channel: ChannelRow[];
}

export function getDashboardSummary(
  date_from: string,
  date_to: string,
): Promise<DashboardSummary> {
  return authFetch<DashboardSummary>('/api/v1/dashboard/summary', {
    date_from,
    date_to,
  });
}

// --- Timeseries ---

export type TimeseriesMetric =
  | 'spend'
  | 'impressions'
  | 'clicks'
  | 'conversions'
  | 'roas';

export interface TimeseriesPoint {
  date: string;
  value: number;
}

export interface TimeseriesResponse {
  metric: string;
  points: TimeseriesPoint[];
}

export function getTimeseries(
  date_from: string,
  date_to: string,
  metric: TimeseriesMetric,
): Promise<TimeseriesResponse> {
  return authFetch<TimeseriesResponse>('/api/v1/dashboard/timeseries', {
    date_from,
    date_to,
    metric,
  });
}
