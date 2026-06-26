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

// Best-effort server-side token revocation; never blocks logout if it fails.
export async function logout(): Promise<void> {
  const token = getToken();
  if (token) {
    try {
      await fetch(`${API_BASE}/api/v1/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      /* ignore — clear locally regardless */
    }
  }
  clearToken();
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

// Comparison response — previous period totals + fractional deltas (0.12 = +12%).
// Fields may be null when the previous period value was 0 (division by zero guard).
export interface Deltas {
  spend: number | null;
  impressions: number | null;
  clicks: number | null;
  conversions: number | null;
  conversion_value: number | null;
  ctr: number | null;
  cpc: number | null;
  cpa: number | null;
  roas: number | null;
}

export interface DashboardSummaryWithCompare extends DashboardSummary {
  previous: Totals;
  deltas: Deltas;
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

export function getDashboardSummaryWithCompare(
  date_from: string,
  date_to: string,
): Promise<DashboardSummaryWithCompare> {
  return authFetch<DashboardSummaryWithCompare>('/api/v1/dashboard/summary', {
    date_from,
    date_to,
    compare: 'true',
  });
}

// --- CSV export (auth-aware) ---

/**
 * Download a CSV from an authenticated endpoint.
 * Uses fetch + Authorization header, converts the response to a Blob,
 * creates a temporary object URL, and triggers an <a download> click.
 * The filename is taken from Content-Disposition when present,
 * otherwise falls back to `fallbackName`.
 */
export async function downloadCsv(
  path: string,
  params: Record<string, string>,
  fallbackName: string,
): Promise<void> {
  const token = getToken();
  const url = new URL(`${API_BASE}${path}`);
  Object.entries(params).forEach(([k, v]) => {
    if (v) url.searchParams.set(k, v);
  });

  const res = await fetch(url.toString(), {
    headers: { Authorization: `Bearer ${token ?? ''}` },
  });

  if (res.status === 401) {
    clearToken();
    if (typeof window !== 'undefined') window.location.href = '/login';
    throw new Error('Oturum süresi doldu');
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => 'Dışa aktarma başarısız');
    throw new Error(detail || 'Dışa aktarma başarısız');
  }

  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') ?? '';
  let filename = fallbackName;
  const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/i);
  if (match) {
    filename = match[1].replace(/['"]/g, '').trim() || fallbackName;
  }

  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
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
