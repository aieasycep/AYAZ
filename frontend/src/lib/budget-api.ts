// Budget Planner API — typed wrappers for /api/v1/budget/*

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

  // DELETE / 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type BudgetObjective =
  | 'balanced'
  | 'maximize_roas'
  | 'maximize_conversions';

export type BudgetStatus = 'draft' | 'active' | 'archived';

export interface CampaignAllocation {
  campaign_id: string;
  name: string;
  recommended_budget: number;
  recommended_share: number;
  roas: number;
  expected_conversions: number;
  expected_revenue: number;
}

export interface PlatformAllocation {
  channel: string;
  label: string;
  historical_spend: number;
  historical_share: number;
  roas: number;
  cpa: number;
  recommended_budget: number;
  recommended_share: number;
  delta_pct: number;
  expected_conversions: number;
  expected_revenue: number;
  expected_roas: number;
  campaigns: CampaignAllocation[];
}

export interface AllocationResult {
  total_budget: number;
  currency: string;
  objective: string;
  lookback_days: number;
  based_on: { date_from: string; date_to: string };
  platforms: PlatformAllocation[];
  projection: {
    expected_conversions: number;
    expected_revenue: number;
    expected_roas: number;
  };
  notes: string[];
}

export interface BudgetPlan {
  id: string;
  tenant_id: string;
  name: string;
  period_month: string;
  total_budget: number;
  currency: string;
  objective: BudgetObjective;
  lookback_days: number;
  allocations: AllocationResult | null;
  status: BudgetStatus;
  created_at: string;
  updated_at: string;
}

// --- Label maps ---

export const OBJECTIVE_LABELS: Record<BudgetObjective, string> = {
  balanced: 'Dengeli',
  maximize_roas: "ROAS'ı Maksimize Et",
  maximize_conversions: 'Dönüşümü Maksimize Et',
};

export const STATUS_LABELS: Record<BudgetStatus, string> = {
  draft: 'Taslak',
  active: 'Aktif',
  archived: 'Arşiv',
};

// --- Preview ---

export interface PreviewBudgetPayload {
  total_budget: number;
  objective?: BudgetObjective;
  lookback_days?: number;
  currency?: string;
}

export function previewBudget(payload: PreviewBudgetPayload): Promise<AllocationResult> {
  return authFetch<AllocationResult>('/api/v1/budget/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// --- Plans CRUD ---

export interface CreateBudgetPlanPayload {
  name: string;
  period_month: string;
  total_budget: number;
  objective?: BudgetObjective;
  lookback_days?: number;
  currency?: string;
}

export function createBudgetPlan(payload: CreateBudgetPlanPayload): Promise<BudgetPlan> {
  return authFetch<BudgetPlan>('/api/v1/budget/plans', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getBudgetPlans(): Promise<BudgetPlan[]> {
  return authFetch<BudgetPlan[]>('/api/v1/budget/plans');
}

export function getBudgetPlan(id: string): Promise<BudgetPlan> {
  return authFetch<BudgetPlan>(`/api/v1/budget/plans/${id}`);
}

export interface PatchBudgetPlanPayload {
  name?: string;
  status?: BudgetStatus;
  total_budget?: number;
  objective?: BudgetObjective;
  lookback_days?: number;
}

export function patchBudgetPlan(id: string, payload: PatchBudgetPlanPayload): Promise<BudgetPlan> {
  return authFetch<BudgetPlan>(`/api/v1/budget/plans/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteBudgetPlan(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/budget/plans/${id}`, {
    method: 'DELETE',
  });
}

export function recomputeBudgetPlan(id: string): Promise<BudgetPlan> {
  return authFetch<BudgetPlan>(`/api/v1/budget/plans/${id}/recompute`, {
    method: 'POST',
  });
}

// --- Plan vs Actuals ---

export interface ActualTotals {
  planned_budget: number;
  actual_spend: number;
  pace_pct: number;
  time_pace_pct: number;
  planned_revenue: number;
  actual_revenue: number;
  actual_conversions: number;
  actual_roas: number;
}

export interface ActualChannel {
  channel: string;
  label: string;
  planned_budget: number;
  planned_share: number;
  actual_spend: number;
  actual_share: number;
  pace_pct: number;
  actual_roas: number;
  actual_revenue: number;
  actual_conversions: number;
  variance_pct: number;
}

export interface PlanActuals {
  plan_id: string;
  period_month: string;
  currency: string;
  as_of: string;
  days_elapsed: number;
  days_in_month: number;
  totals: ActualTotals;
  channels: ActualChannel[];
  notes: string[];
}

export function getPlanActuals(planId: string): Promise<PlanActuals> {
  return authFetch<PlanActuals>(`/api/v1/budget/plans/${planId}/actuals`);
}
