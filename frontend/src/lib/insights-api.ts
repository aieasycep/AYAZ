// Insights & Alert Rules API — typed wrappers for /api/v1/insights/*

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

export type InsightSeverity = 'critical' | 'warning' | 'info';
export type InsightStatus = 'new' | 'seen' | 'dismissed';

export interface Insight {
  id: string;
  category: string;
  severity: InsightSeverity;
  title: string;
  body: string;
  metric: string | null;
  channel: string | null;
  entity_name: string | null;
  period_start: string | null; // ISO date
  period_end: string | null;   // ISO date
  status: InsightStatus;
  score: number;
  created_at: string;
}

export interface GenerateResponse {
  counts: Record<string, number>;
}

export type AlertComparator =
  | 'pct_drop'
  | 'pct_rise'
  | 'below'
  | 'above'
  | 'anomaly';

export type AlertDelivery = 'email' | 'slack' | 'none';

export interface AlertRule {
  id: string;
  name: string;
  metric: string;
  comparator: AlertComparator;
  threshold: number | null;
  delivery: AlertDelivery;
  destination: string | null;
  active: boolean;
  created_at: string;
}

export interface CreateAlertRulePayload {
  name: string;
  metric: string;
  comparator: AlertComparator;
  threshold: number | null;
  delivery: AlertDelivery;
  destination: string | null;
  active: boolean;
}

export interface UpdateAlertRulePayload {
  name?: string;
  metric?: string;
  comparator?: AlertComparator;
  threshold?: number | null;
  delivery?: AlertDelivery;
  destination?: string | null;
  active?: boolean;
}

// --- Insights API ---

export function getInsights(params?: {
  severity?: InsightSeverity | '';
  status?: InsightStatus | 'all' | '';
}): Promise<Insight[]> {
  const qs = new URLSearchParams();
  if (params?.severity) qs.set('severity', params.severity);
  if (params?.status && params.status !== 'all') qs.set('status', params.status);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return authFetch<Insight[]>(`/api/v1/insights${query}`);
}

export function patchInsight(
  id: string,
  payload: { status: InsightStatus },
): Promise<Insight> {
  return authFetch<Insight>(`/api/v1/insights/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function generateInsights(): Promise<GenerateResponse> {
  return authFetch<GenerateResponse>('/api/v1/insights/generate', {
    method: 'POST',
  });
}

// --- Alert Rules API ---

export function getAlertRules(): Promise<AlertRule[]> {
  return authFetch<AlertRule[]>('/api/v1/insights/alert-rules');
}

export function createAlertRule(
  payload: CreateAlertRulePayload,
): Promise<AlertRule> {
  return authFetch<AlertRule>('/api/v1/insights/alert-rules', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function patchAlertRule(
  id: string,
  payload: UpdateAlertRulePayload,
): Promise<AlertRule> {
  return authFetch<AlertRule>(`/api/v1/insights/alert-rules/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteAlertRule(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/insights/alert-rules/${id}`, {
    method: 'DELETE',
  });
}
