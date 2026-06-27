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
export type InsightReaction = 'up' | 'down';

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
  applied_at: string | null;
  reaction: InsightReaction | null;
}

// Backend returns {as_of_date, new_info, new_warning, new_critical, skipped}.
export interface GenerateResponse {
  as_of_date?: string;
  new_info?: number;
  new_warning?: number;
  new_critical?: number;
  skipped?: number;
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

// --- Normalisation ---
// Backend AlertRule uses `is_active`; the UI reads/writes `active`. Translate
// both directions so the page can keep using `active`.
function normaliseAlertRule(r: AlertRule & { is_active?: boolean }): AlertRule {
  if (r && typeof r.is_active === 'boolean' && r.active === undefined) {
    r.active = r.is_active;
  }
  return r;
}

function rulePayloadToBackend<T extends { active?: boolean }>(
  payload: T,
): Omit<T, 'active'> & { is_active?: boolean } {
  const { active, ...rest } = payload;
  return active === undefined ? rest : { ...rest, is_active: active };
}

// --- Insights API ---

export function getInsights(params?: {
  severity?: InsightSeverity | '';
  status?: InsightStatus | 'all' | '';
  applied?: boolean;
  reaction?: InsightReaction;
}): Promise<Insight[]> {
  const qs = new URLSearchParams();
  if (params?.severity) qs.set('severity', params.severity);
  if (params?.status && params.status !== 'all') qs.set('status', params.status);
  if (params?.applied !== undefined) qs.set('applied', String(params.applied));
  if (params?.reaction) qs.set('reaction', params.reaction);
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return authFetch<Insight[]>(`/api/v1/insights${query}`);
}

export function applyInsight(
  id: string,
  applied: boolean,
): Promise<Insight> {
  return authFetch<Insight>(`/api/v1/insights/${id}/apply`, {
    method: 'POST',
    body: JSON.stringify({ applied }),
  });
}

export function reactInsight(
  id: string,
  reaction: InsightReaction | null,
): Promise<Insight> {
  return authFetch<Insight>(`/api/v1/insights/${id}/react`, {
    method: 'POST',
    body: JSON.stringify({ reaction }),
  });
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

export async function getAlertRules(): Promise<AlertRule[]> {
  const rules = await authFetch<AlertRule[]>('/api/v1/insights/alert-rules');
  return rules.map(normaliseAlertRule);
}

export async function createAlertRule(
  payload: CreateAlertRulePayload,
): Promise<AlertRule> {
  return normaliseAlertRule(
    await authFetch<AlertRule>('/api/v1/insights/alert-rules', {
      method: 'POST',
      body: JSON.stringify(rulePayloadToBackend(payload)),
    }),
  );
}

export async function patchAlertRule(
  id: string,
  payload: UpdateAlertRulePayload,
): Promise<AlertRule> {
  return normaliseAlertRule(
    await authFetch<AlertRule>(`/api/v1/insights/alert-rules/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(rulePayloadToBackend(payload)),
    }),
  );
}

export function deleteAlertRule(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/insights/alert-rules/${id}`, {
    method: 'DELETE',
  });
}

// --- Root-cause & one-click fixes ---

export type FixActionType =
  | 'create_alert_rule'
  | 'create_goal'
  | 'view_campaign'
  | 'dismiss';

export interface FixAction {
  label: string;
  action_type: FixActionType;
  payload: Record<string, unknown>;
}

export interface InsightFixes {
  root_cause: string;
  fixes: FixAction[];
}

// Backend returns {action_type, success, message, entity_id?, entity_type?}.
export interface ApplyFixResponse {
  action_type: string;
  success: boolean;
  message: string;
  entity_id?: string | null;
  entity_type?: string | null;
}

export function getInsightFixes(id: string): Promise<InsightFixes> {
  return authFetch<InsightFixes>(`/api/v1/insights/${id}/fixes`);
}

export function applyInsightFix(
  id: string,
  action_type: FixActionType,
  payload: Record<string, unknown>,
): Promise<ApplyFixResponse> {
  return authFetch<ApplyFixResponse>(`/api/v1/insights/${id}/fixes/apply`, {
    method: 'POST',
    body: JSON.stringify({ action_type, payload }),
  });
}
