// Budget Optimizer API — typed wrappers for /api/v1/optimizer/*

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

export interface ChannelAllocation {
  channel: string;
  spend: number;
  roas: number;
  share_of_spend: number;
  [key: string]: unknown;
}

export interface BudgetSuggestion {
  from_channel: string;
  to_channel: string;
  amount: number;
  from_roas: number;
  to_roas: number;
  projected_conversion_value_delta: number;
  rationale: string;
}

export interface OptimizerSummary {
  total_shift: number;
  projected_uplift: number;
}

export interface BudgetOptimizationResult {
  current_allocation: ChannelAllocation[];
  suggestions: BudgetSuggestion[];
  summary: OptimizerSummary;
  caveat: string;
}

export interface GetBudgetOptimizationParams {
  date_from?: string;
  date_to?: string;
  max_shift_pct?: number;
}

// --- API functions ---

export function getBudgetOptimization(
  params?: GetBudgetOptimizationParams,
): Promise<BudgetOptimizationResult> {
  const qs = new URLSearchParams();
  if (params?.date_from) qs.set('date_from', params.date_from);
  if (params?.date_to) qs.set('date_to', params.date_to);
  if (params?.max_shift_pct != null)
    qs.set('max_shift_pct', String(params.max_shift_pct));
  const query = qs.toString() ? `?${qs.toString()}` : '';
  return authFetch<BudgetOptimizationResult>(`/api/v1/optimizer/budget${query}`);
}
