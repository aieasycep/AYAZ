// Executive / CMO Overview API — typed wrappers for /api/v1/executive/*

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

export interface KpiDeltas {
  spend_pct: number | null;
  revenue_pct: number | null;
  conversions_pct: number | null;
  roas_pct: number | null;
}

export interface Kpis {
  spend: number;
  revenue: number;
  conversions: number;
  clicks: number;
  roas: number;
  deltas: KpiDeltas;
}

export interface ChannelRoi {
  channel: string;
  label: string;
  spend: number;
  revenue: number;
  roas: number;
  share_pct: number;
}

export interface ExecGoal {
  name: string;
  metric: string;
  current_value: number;
  target_value: number;
  pct_to_target: number;
  status: string;
}

export interface ExecInsight {
  severity: string;
  title: string;
  channel: string | null;
}

export interface ExecutiveOverview {
  period: {
    date_from: string;
    date_to: string;
    prev_date_from: string;
    prev_date_to: string;
  };
  kpis: Kpis;
  channels: ChannelRoi[];
  goals: ExecGoal[];
  insights: ExecInsight[];
  headline: string;
}

// --- API functions ---

export interface GetExecutiveOverviewOptions {
  date_from?: string;
  date_to?: string;
}

export function getExecutiveOverview(
  opts: GetExecutiveOverviewOptions = {},
): Promise<ExecutiveOverview> {
  const params = new URLSearchParams();
  if (opts.date_from) params.set('date_from', opts.date_from);
  if (opts.date_to) params.set('date_to', opts.date_to);
  const qs = params.toString();
  return authFetch<ExecutiveOverview>(
    `/api/v1/executive/overview${qs ? `?${qs}` : ''}`,
  );
}
