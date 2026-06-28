// Command Center API — typed wrappers for /api/v1/command-center/*

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

export type AttentionSeverity = 'critical' | 'warning' | 'info';

export interface AttentionItem {
  severity: AttentionSeverity;
  title: string;
  detail: string;
  module: string;
  link: string;
}

export interface CcKpis {
  spend: number;
  revenue: number;
  roas: number;
  conversions: number;
  deltas: {
    spend_pct: number | null;
    revenue_pct: number | null;
    roas_pct: number | null;
    conversions_pct: number | null;
  };
}

export interface CcModules {
  budget: {
    has_plan: boolean;
    period_month: string | null;
    pace_pct: number | null;
    pace_status: string | null;
  };
  inbox: {
    total: number;
    open: number;
    pending: number;
    negative: number;
  };
  content: {
    draft: number;
    pending_approval: number;
    scheduled: number;
  };
  goals: {
    total: number;
    at_risk: number;
  };
  insights: {
    critical: number;
    warning: number;
  };
}

export interface CommandCenter {
  headline: string;
  kpis: CcKpis;
  attention: AttentionItem[];
  modules: CcModules;
}

// --- API function ---

export function getCommandCenter(): Promise<CommandCenter> {
  return authFetch<CommandCenter>('/api/v1/command-center/overview');
}
