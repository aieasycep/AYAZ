// Billing & Subscription API — typed wrappers for /api/v1/billing/*

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

  // 204 No Content — return undefined cast to T
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export interface PlanLimits {
  data_sources: number | null; // null = unlimited
  [key: string]: number | string | boolean | null | undefined;
}

export interface Plan {
  code: string;
  name: string;
  price_try: number;
  price_usd: number;
  limits: PlanLimits;
  features: string[];
}

export type SubscriptionStatus =
  | 'trialing'
  | 'active'
  | 'past_due'
  | 'canceled'
  | 'unknown';

export interface SubscriptionUsage {
  data_sources_used: number;
}

export interface Subscription {
  plan_code: string;
  status: SubscriptionStatus;
  trial_end: string | null;       // ISO date-time
  current_period_end: string | null; // ISO date-time
  entitlements: Record<string, boolean | number | string>;
  usage: SubscriptionUsage;
}

export interface CheckoutResponse {
  checkout_url: string;
}

// --- API functions ---

// Backend exposes limits.max_data_sources (number | "unlimited"); the UI reads
// limits.data_sources (number | null). Normalize on the client so the page stays simple.
export async function getPlans(): Promise<Plan[]> {
  const plans = await authFetch<Plan[]>('/api/v1/billing/plans');
  return plans.map((p) => {
    const max = (p.limits as Record<string, unknown>)?.max_data_sources;
    const data_sources =
      max === 'unlimited' || max === null || max === undefined ? null : Number(max);
    return { ...p, limits: { ...p.limits, data_sources } };
  });
}

// Backend returns data_sources_used at the top level; the UI reads subscription.usage.data_sources_used.
export async function getSubscription(): Promise<Subscription> {
  const raw = await authFetch<
    Omit<Subscription, 'usage'> & { data_sources_used?: number; usage?: SubscriptionUsage }
  >('/api/v1/billing/subscription');
  return {
    ...raw,
    usage: {
      data_sources_used: raw.usage?.data_sources_used ?? raw.data_sources_used ?? 0,
    },
  };
}

export function postCheckout(plan_code: string): Promise<CheckoutResponse> {
  return authFetch<CheckoutResponse>('/api/v1/billing/checkout', {
    method: 'POST',
    body: JSON.stringify({ plan_code }),
  });
}

export function postCancel(): Promise<void> {
  return authFetch<void>('/api/v1/billing/cancel', {
    method: 'POST',
  });
}
