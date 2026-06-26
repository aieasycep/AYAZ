// Goals & Forecasting API — typed wrappers for /api/v1/goals/*

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

export type GoalMetric = 'spend' | 'roas' | 'conversions' | 'conversion_value';
export type GoalStatus = 'on_track' | 'at_risk' | 'off_track';

export interface Goal {
  id: string;
  name: string;
  metric: GoalMetric;
  target_value: number;
  period: string; // e.g. "ay"
  period_start: string; // ISO date
  period_end: string;   // ISO date
  channel: string | null;
  created_at: string;
}

export interface GoalProgress {
  current_value: number;
  target_value: number;
  pct_to_target: number;
  forecast_value: number;
  expected_pace_value: number;
  status: GoalStatus;
  recommendation: string;
  days_elapsed: number;
  days_total: number;
}

export interface CreateGoalPayload {
  name: string;
  metric: GoalMetric;
  target_value: number;
  period: string;
  period_start: string;
  period_end: string;
  channel?: string | null;
}

export interface UpdateGoalPayload {
  name?: string;
  metric?: GoalMetric;
  target_value?: number;
  period?: string;
  period_start?: string;
  period_end?: string;
  channel?: string | null;
}

// --- API functions ---

export function getGoals(): Promise<Goal[]> {
  return authFetch<Goal[]>('/api/v1/goals');
}

export function createGoal(payload: CreateGoalPayload): Promise<Goal> {
  return authFetch<Goal>('/api/v1/goals', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getGoal(id: string): Promise<Goal> {
  return authFetch<Goal>(`/api/v1/goals/${id}`);
}

export function patchGoal(id: string, payload: UpdateGoalPayload): Promise<Goal> {
  return authFetch<Goal>(`/api/v1/goals/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteGoal(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/goals/${id}`, {
    method: 'DELETE',
  });
}

export function getGoalProgress(id: string): Promise<GoalProgress> {
  return authFetch<GoalProgress>(`/api/v1/goals/${id}/progress`);
}
