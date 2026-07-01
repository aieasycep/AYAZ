// Reports API — typed wrappers for /api/v1/reports/*

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

  // DELETE returns 204 — no body
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export interface ReportWhiteLabel {
  brand_name?: string;
  logo_url?: string;
  color?: string;
}

export interface ReportConfig {
  metrics?: string[];
  channels?: string[];
  white_label?: ReportWhiteLabel;
}

export interface ReportDefinition {
  id: string;
  name: string;
  config: ReportConfig;
  created_at: string;
  updated_at?: string;
}

export interface CreateReportPayload {
  name: string;
  config: ReportConfig;
}

export interface UpdateReportPayload {
  name?: string;
  config?: ReportConfig;
}

// Preview

export interface ReportTotals {
  spend?: number;
  impressions?: number;
  clicks?: number;
  conversions?: number;
  conversion_value?: number;
  ctr?: number;
  cpc?: number;
  cpa?: number;
  roas?: number;
}

export interface ReportChannelRow {
  channel: string;
  spend?: number;
  impressions?: number;
  clicks?: number;
  conversions?: number;
  conversion_value?: number;
  ctr?: number;
  cpc?: number;
  cpa?: number;
  roas?: number;
}

export interface ReportTimeseriesPoint {
  date: string;
  value: number;
}

export interface ReportPreview {
  totals: ReportTotals;
  by_channel: ReportChannelRow[];
  timeseries: ReportTimeseriesPoint[];
}

// Share

export interface ShareResponse {
  public_url: string;
  public_token: string;
}

// Schedule

export type ReportCadence = 'daily' | 'weekly' | 'monthly';

export interface ReportSchedule {
  id: string;
  report_definition_id: string;
  cadence: ReportCadence;
  weekday?: number | null; // 0=Mon … 6=Sun, for weekly
  hour: number;
  delivery?: string;
  recipients: string[];
  is_active?: boolean;
  created_at: string;
}

export interface CreateSchedulePayload {
  cadence: ReportCadence;
  weekday?: number | null;
  hour: number;
  recipients: string[];
}

// --- API functions ---

export function getReports(): Promise<ReportDefinition[]> {
  return authFetch<ReportDefinition[]>('/api/v1/reports/definitions');
}

export function createReport(payload: CreateReportPayload): Promise<ReportDefinition> {
  return authFetch<ReportDefinition>('/api/v1/reports/definitions', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getReport(id: string): Promise<ReportDefinition> {
  return authFetch<ReportDefinition>(`/api/v1/reports/definitions/${id}`);
}

export function updateReport(
  id: string,
  payload: UpdateReportPayload,
): Promise<ReportDefinition> {
  return authFetch<ReportDefinition>(`/api/v1/reports/definitions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteReport(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/reports/definitions/${id}`, {
    method: 'DELETE',
  });
}

export function previewReport(
  id: string,
  date_from: string,
  date_to: string,
): Promise<ReportPreview> {
  const qs = new URLSearchParams({ date_from, date_to });
  return authFetch<ReportPreview>(`/api/v1/reports/definitions/${id}/preview?${qs}`);
}

export function shareReport(id: string): Promise<ShareResponse> {
  return authFetch<ShareResponse>(`/api/v1/reports/definitions/${id}/share`, {
    method: 'POST',
  });
}

// Backend lists all tenant schedules at /reports/schedules; filter by report client-side.
export async function getSchedules(reportId: string): Promise<ReportSchedule[]> {
  const all = await authFetch<ReportSchedule[]>('/api/v1/reports/schedules');
  return all.filter((s) => s.report_definition_id === reportId);
}

export function createSchedule(
  reportId: string,
  payload: CreateSchedulePayload,
): Promise<ReportSchedule> {
  return authFetch<ReportSchedule>('/api/v1/reports/schedules', {
    method: 'POST',
    body: JSON.stringify({
      report_definition_id: reportId,
      delivery: 'email',
      ...payload,
    }),
  });
}

// --- Public report URL helper ---

export function getPublicReportUrl(token: string): string {
  return `${API_BASE}/api/v1/reports/public/${token}`;
}
