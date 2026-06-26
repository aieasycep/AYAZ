// Report Builder API — typed wrappers for /api/v1/reports/*

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

export interface ReportSpec {
  title: string;
  metrics: string[];
  channels: string[];
  comparison: boolean;
  viz: string;
}

export interface ReportTotals {
  [metric: string]: number;
}

export interface ReportTimeseriesPoint {
  date: string;
  value: number;
}

export interface ReportChannelRow {
  channel: string;
  spend?: number;
  impressions?: number;
  clicks?: number;
  conversions?: number;
  roas?: number;
  cpc?: number;
  ctr?: number;
  [key: string]: number | string | undefined;
}

export interface BuildReportResponse {
  spec: ReportSpec;
  data: {
    totals: ReportTotals;
    by_channel: ReportChannelRow[];
    timeseries: ReportTimeseriesPoint[];
  };
}

export interface BuildReportPayload {
  prompt: string;
  date_from?: string;
  date_to?: string;
}

export interface SaveReportDefinitionPayload {
  name: string;
  config: {
    metrics: string[];
    channels: string[];
  };
}

export interface SaveReportDefinitionResponse {
  id: string;
  name: string;
}

// --- API functions ---

export function buildReport(payload: BuildReportPayload): Promise<BuildReportResponse> {
  return authFetch<BuildReportResponse>('/api/v1/reports/build', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function saveReportDefinition(
  payload: SaveReportDefinitionPayload,
): Promise<SaveReportDefinitionResponse> {
  return authFetch<SaveReportDefinitionResponse>('/api/v1/reports/definitions', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
