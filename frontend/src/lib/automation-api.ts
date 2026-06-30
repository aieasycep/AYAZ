// Automation Rules API — typed wrappers for /api/v1/automation/*

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

  // DELETE returns 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type AutomationScope = 'account' | 'channel' | 'campaign';

export type AutomationMetric =
  | 'spend'
  | 'roas'
  | 'ctr'
  | 'cpc'
  | 'cpa'
  | 'conversions';

export type AutomationComparator =
  | 'pct_drop'
  | 'pct_rise'
  | 'below'
  | 'above'
  | 'anomaly';

export type AutomationAction =
  | 'alert'
  | 'notify_email'
  | 'notify_slack'
  | 'pause_suggest';

export interface AutomationRule {
  id: string;
  name: string;
  scope: AutomationScope;
  scope_filter: string | null;
  metric: AutomationMetric;
  comparator: AutomationComparator;
  threshold: number | null;
  window_days: number;
  action: AutomationAction;
  action_config: Record<string, string> | null;
  is_active: boolean;
  last_triggered_at: string | null;
}

export interface CreateAutomationRulePayload {
  name: string;
  scope: AutomationScope;
  scope_filter: string | null;
  metric: AutomationMetric;
  comparator: AutomationComparator;
  threshold: number | null;
  window_days: number;
  action: AutomationAction;
  action_config: Record<string, string> | null;
  is_active: boolean;
}

export type UpdateAutomationRulePayload = Partial<CreateAutomationRulePayload>;

// Backend `detail` is a structured object (dict). The error path in the page
// sets it to a string, so accept both.
export type RunDetail = Record<string, unknown> | string;

export interface RunResult {
  triggered: boolean;
  detail: RunDetail;
}

export interface RuleRun {
  ran_at: string;
  triggered: boolean;
  detail: RunDetail;
}

// --- API functions ---

export function getAutomationRules(): Promise<AutomationRule[]> {
  return authFetch<AutomationRule[]>('/api/v1/automation/rules');
}

export function createAutomationRule(
  payload: CreateAutomationRulePayload,
): Promise<AutomationRule> {
  return authFetch<AutomationRule>('/api/v1/automation/rules', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getAutomationRule(id: string): Promise<AutomationRule> {
  return authFetch<AutomationRule>(`/api/v1/automation/rules/${id}`);
}

export function patchAutomationRule(
  id: string,
  payload: UpdateAutomationRulePayload,
): Promise<AutomationRule> {
  return authFetch<AutomationRule>(`/api/v1/automation/rules/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteAutomationRule(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/automation/rules/${id}`, {
    method: 'DELETE',
  });
}

export function runAutomationRule(id: string): Promise<RunResult> {
  return authFetch<RunResult>(`/api/v1/automation/rules/${id}/run`, {
    method: 'POST',
  });
}

export function getAutomationRuleRuns(id: string): Promise<RuleRun[]> {
  return authFetch<RuleRun[]>(`/api/v1/automation/rules/${id}/runs`);
}
