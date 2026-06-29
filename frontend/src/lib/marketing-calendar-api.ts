// Marketing Calendar API — typed wrappers for /api/v1/marketing-calendar/*

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

  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type OppCategory = 'ticari' | 'resmi' | 'sezonsal' | 'dini';
export type CommerceWeight = 'yuksek' | 'orta' | 'dusuk';
export type OppStatus = 'urgent' | 'upcoming';

export const CATEGORY_LABELS: Record<OppCategory, string> = {
  ticari: 'Ticari',
  resmi: 'Resmi',
  sezonsal: 'Sezonsal',
  dini: 'Dini',
};

export const WEIGHT_LABELS: Record<CommerceWeight, string> = {
  yuksek: 'Yüksek',
  orta: 'Orta',
  dusuk: 'Düşük',
};

export interface OpportunityReadiness {
  content_scheduled: number;
  budget_planned: boolean;
}

export interface OpportunityAction {
  label: string;
  href: string;
}

export interface Opportunity {
  date: string;
  name: string;
  category: OppCategory;
  commerce_weight: CommerceWeight;
  is_approximate: boolean;
  days_until: number;
  lead_time_days: number;
  status: OppStatus;
  marketing_tip: string;
  readiness: OpportunityReadiness;
  suggested_actions: OpportunityAction[];
}

export interface OpportunityCalendarSummary {
  total: number;
  urgent: number;
  this_month: number;
  high_weight: number;
}

export interface OpportunityCalendar {
  as_of: string;
  horizon_months: number;
  summary: OpportunityCalendarSummary;
  opportunities: Opportunity[];
}

// --- API functions ---

export function getOpportunities(horizonMonths?: number): Promise<OpportunityCalendar> {
  const params = new URLSearchParams();
  if (horizonMonths !== undefined) {
    params.set('horizon_months', String(horizonMonths));
  }
  const qs = params.toString();
  return authFetch<OpportunityCalendar>(
    `/api/v1/marketing-calendar/opportunities${qs ? `?${qs}` : ''}`,
  );
}
