// Recommendations API — typed wrappers for /api/v1/recommendations/*

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

export type RecommendationImpact = 'high' | 'medium' | 'low';
export type RecommendationEffort = 'low' | 'medium' | 'high';
export type RecommendationStatus = 'open' | 'accepted' | 'snoozed' | 'dismissed';
export type RecommendationCategory =
  | 'budget'
  | 'performance'
  | 'tracking'
  | 'content'
  | 'inbox'
  | 'goal'
  | 'audit'
  | 'benchmark';

export const IMPACT_LABELS: Record<RecommendationImpact, string> = {
  high: 'Yüksek etki',
  medium: 'Orta etki',
  low: 'Düşük etki',
};

export const EFFORT_LABELS: Record<RecommendationEffort, string> = {
  low: 'Düşük çaba',
  medium: 'Orta çaba',
  high: 'Yüksek çaba',
};

export const STATUS_LABELS: Record<RecommendationStatus, string> = {
  open: 'Açık',
  accepted: 'Kabul edildi',
  snoozed: 'Ertelendi',
  dismissed: 'Reddedildi',
};

export const CATEGORY_LABELS: Record<RecommendationCategory, string> = {
  budget: 'Bütçe',
  performance: 'Performans',
  tracking: 'Ölçümleme',
  content: 'İçerik',
  inbox: 'Gelen Kutusu',
  goal: 'Hedef',
  audit: 'Denetim',
  benchmark: 'Kıyaslama',
};

export interface RecommendationMetric {
  label: string;
  value: string;
}

export interface Recommendation {
  key: string;
  category: RecommendationCategory;
  category_label: string;
  title: string;
  rationale: string;
  impact: RecommendationImpact;
  impact_label: string;
  effort: RecommendationEffort;
  effort_label: string;
  metric: RecommendationMetric | null;
  action_label: string;
  action_href: string;
  status: RecommendationStatus;
  snoozed_until: string | null;
}

export interface RecommendationSummary {
  open: number;
  accepted: number;
  snoozed: number;
  dismissed: number;
  total: number;
  high_impact_open: number;
}

export interface RecommendationFeed {
  generated_at: string;
  summary: RecommendationSummary;
  recommendations: Recommendation[];
}

export interface FocusArea {
  title: string;
  detail: string;
}

export interface WeeklyStrategy {
  week_label: string;
  headline: string;
  narrative: string;
  focus_areas: FocusArea[];
  top_recommendations: Recommendation[];
  source: 'ai' | 'template';
}

export interface RecommendationActionRequest {
  action: 'accept' | 'snooze' | 'dismiss' | 'reopen';
  note?: string;
  snooze_days?: number;
}

export interface RecommendationActionResult {
  key: string;
  status: RecommendationStatus;
  snoozed_until: string | null;
  note: string | null;
}

// --- API functions ---

export function getRecommendationFeed(): Promise<RecommendationFeed> {
  return authFetch<RecommendationFeed>('/api/v1/recommendations/feed');
}

export function getWeeklyStrategy(): Promise<WeeklyStrategy> {
  return authFetch<WeeklyStrategy>('/api/v1/recommendations/weekly-strategy');
}

export function applyRecommendationAction(
  key: string,
  req: RecommendationActionRequest,
): Promise<RecommendationActionResult> {
  const encodedKey = encodeURIComponent(key);
  return authFetch<RecommendationActionResult>(
    `/api/v1/recommendations/${encodedKey}/action`,
    {
      method: 'POST',
      body: JSON.stringify(req),
    },
  );
}
