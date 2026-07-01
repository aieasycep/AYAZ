// Budget Simulator API — typed wrappers for /api/v1/budget-simulator/*

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

  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export interface SimBaselineChannel {
  key: string;
  label: string;
  spend: number;
  impressions: number;
  clicks: number;
  conversions: number;
  conversion_value: number;
  cpc: number;
  cpm: number;
  cvr: number;
  roas: number;
  aov: number;
  cpa: number;
  spend_share_pct: number;
}

export interface SimTotals {
  spend: number;
  impressions: number;
  clicks: number;
  conversions: number;
  conversion_value: number;
  roas: number;
  cpc: number;
  cvr: number;
  cpa: number;
}

export interface SimBaseline {
  lookback_days: number;
  period: { date_from: string; date_to: string };
  total_spend: number;
  channels: SimBaselineChannel[];
  totals: SimTotals;
}

export interface SimChannel {
  key: string;
  label: string;
  spend: number;
  impressions: number;
  clicks: number;
  conversions: number;
  conversion_value: number;
  roas: number;
  cpa: number;
  baseline_spend: number;
  spend_delta: number;
  spend_delta_pct: number;
}

export interface SimDeltas {
  impressions_pct: number;
  clicks_pct: number;
  conversions_pct: number;
  conversion_value_pct: number;
  roas_pct: number;
}

export interface SimResult {
  lookback_days: number;
  total_spend: number;
  channels: SimChannel[];
  projected_totals: SimTotals;
  baseline_totals: SimTotals;
  deltas: SimDeltas;
  assumptions: string[];
}

export interface SimulateRequest {
  allocations: Record<string, number>;
  lookback_days?: number;
}

// --- API functions ---

export function getBaseline(lookbackDays?: number): Promise<SimBaseline> {
  const qs =
    lookbackDays !== undefined ? `?lookback_days=${lookbackDays}` : '';
  return authFetch<SimBaseline>(`/api/v1/budget-simulator/baseline${qs}`);
}

export function simulate(
  allocations: Record<string, number>,
  lookbackDays?: number,
): Promise<SimResult> {
  const body: SimulateRequest = { allocations };
  if (lookbackDays !== undefined) body.lookback_days = lookbackDays;
  return authFetch<SimResult>('/api/v1/budget-simulator/simulate', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
