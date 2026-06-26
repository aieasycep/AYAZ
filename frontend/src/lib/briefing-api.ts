// Briefing API — typed wrappers for /api/v1/briefings/*

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

export type GoalStatus = 'on_track' | 'at_risk' | 'behind';

export interface PerformanceDelta {
  spend?: { value: number; prev: number; pct: number };
  roas?: { value: number; prev: number; pct: number };
  conversions?: { value: number; prev: number; pct: number };
  [key: string]: { value: number; prev: number; pct: number } | undefined;
}

export interface TopInsight {
  severity: 'critical' | 'warning' | 'info';
  title: string;
}

export interface TopRecommendation {
  message: string;
  suggested_action: string;
}

export interface GoalStatusItem {
  name: string;
  status: GoalStatus;
  forecast: string;
}

export interface BriefingBody {
  performance_delta: PerformanceDelta;
  top_insights: TopInsight[];
  top_recommendation: TopRecommendation;
  goals_status: GoalStatusItem[];
}

export interface Briefing {
  id: string;
  briefing_date: string; // ISO date
  headline: string;
  body: BriefingBody;
}

export interface BriefingSummary {
  id: string;
  briefing_date: string;
  headline: string;
}

// --- API calls ---

export function getLatestBriefing(): Promise<Briefing> {
  return authFetch<Briefing>('/api/v1/briefings/latest');
}

export function getBriefings(): Promise<BriefingSummary[]> {
  return authFetch<BriefingSummary[]>('/api/v1/briefings');
}

export function generateBriefing(): Promise<Briefing> {
  return authFetch<Briefing>('/api/v1/briefings/generate', {
    method: 'POST',
  });
}
