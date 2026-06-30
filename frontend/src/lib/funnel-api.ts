// Funnel API — typed wrappers for /api/v1/funnel/*

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

export interface FunnelStage {
  key: string;
  label: string;
  count: number;
  conversion_from_prev_pct: number | null;
  dropoff_count: number;
  dropoff_pct: number | null;
  share_of_entry_pct: number;
}

export interface FunnelBiggestDropoff {
  from_label: string;
  to_label: string;
  dropoff_pct: number;
}

export interface FunnelOverview {
  period: { date_from: string; date_to: string };
  total_events: number;
  stages: FunnelStage[];
  entry_count: number;
  final_count: number;
  overall_conversion_pct: number;
  biggest_dropoff: FunnelBiggestDropoff | null;
}

// --- API functions ---

export function getFunnel(
  dateFrom?: string,
  dateTo?: string,
): Promise<FunnelOverview> {
  const params = new URLSearchParams();
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  const qs = params.toString();
  const path = `/api/v1/funnel/overview${qs ? `?${qs}` : ''}`;
  return authFetch<FunnelOverview>(path);
}
