// SEO API — typed client for /api/v1/seo/* endpoints.
// Auth pattern mirrors integrations-api.ts: Bearer ayaz_token from localStorage.

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

// ── Types ──────────────────────────────────────────────────────────────────────

export interface SeoOverviewTotals {
  clicks: number;
  impressions: number;
  ctr: number;
  avg_position: number;
}

export interface SeoOverviewTrends {
  clicks_delta_pct: number | null;
  impressions_delta_pct: number | null;
  ctr_delta_pct: number | null;
  position_delta_pct: number | null;
}

export interface SeoTopQuery {
  query: string;
  clicks: number;
  impressions: number;
  ctr: number;
  avg_position: number;
}

export interface SeoTopPage {
  page: string;
  clicks: number;
  impressions: number;
  ctr: number;
  avg_position: number;
}

export interface SeoOverviewResponse {
  period_days: number;
  current: SeoOverviewTotals;
  prior: SeoOverviewTotals;
  trends: SeoOverviewTrends;
  top_queries: SeoTopQuery[];
  top_pages: SeoTopPage[];
}

// Opportunity types from backend seo.py
export type SeoOpportunityType =
  | 'striking_distance'
  | 'low_ctr'
  | 'cannibalization'
  | 'top_movers';

export type SeoSeverity = 'critical' | 'warning' | 'info';

export interface SeoOpportunity {
  type: SeoOpportunityType;
  severity: SeoSeverity;
  title: string;
  body: string;
  data: Record<string, unknown>;
}

export interface SeoOpportunitiesResponse {
  opportunities: SeoOpportunity[];
  count: number;
  emitted: Record<string, number> | null;
}

// Audit
export type AuditStatus = 'ok' | 'kimlik_bekliyor' | 'error';

export interface CoreWebVital {
  value: number | null;
  unit: string;
  score: number | null;  // 0–100
}

export interface SeoAuditCoreWebVitals {
  lcp: CoreWebVital;
  cls: CoreWebVital;
  fcp: CoreWebVital;
  ttfb: CoreWebVital;
}

export interface SeoAuditLighthouseScores {
  performance: number | null;
  seo: number | null;
  accessibility: number | null;
  best_practices: number | null;
}

export interface SeoAuditIssue {
  id: string;
  title: string;
  description?: string;
  score: number | null;
}

export interface SeoAuditResponse {
  status: AuditStatus;
  url?: string;
  strategy?: string;
  core_web_vitals?: SeoAuditCoreWebVitals;
  lighthouse_scores?: SeoAuditLighthouseScores;
  issues?: SeoAuditIssue[];
  message?: string;
}

// DataForSEO gated endpoints
export type SeoGatedStatus = 'connect_required' | 'error' | 'ok';

export interface BacklinksConnectRequired {
  status: 'connect_required';
  message: string;
  integration_key: string;
}

export interface BacklinksSummary {
  status: 'ok';
  domain: string;
  total_backlinks: number;
  referring_domains: number;
  [key: string]: unknown;
}

export type SeoBacklinksResponse = BacklinksConnectRequired | BacklinksSummary | { status: 'error'; message: string };

export interface KeywordsConnectRequired {
  status: 'connect_required';
  message: string;
  integration_key: string;
}

export interface KeywordIdea {
  keyword: string;
  volume: number;
  difficulty: number;
  [key: string]: unknown;
}

export interface KeywordsResult {
  status: 'ok';
  seed: string;
  items: KeywordIdea[];
}

export type SeoKeywordsResponse = KeywordsConnectRequired | KeywordsResult | { status: 'error'; message: string };

// ── Label maps ─────────────────────────────────────────────────────────────────

export const OPPORTUNITY_TYPE_LABELS: Record<SeoOpportunityType, string> = {
  striking_distance: 'Sıçrama mesafesi',
  low_ctr: 'Yüksek gösterim · düşük CTR',
  cannibalization: 'İçerik yamyamlığı',
  top_movers: 'En çok değişenler',
};

export const SEVERITY_LABELS: Record<SeoSeverity, string> = {
  critical: 'Kritik',
  warning: 'Uyarı',
  info: 'Bilgi',
};

// ── API Functions ──────────────────────────────────────────────────────────────

export function getSeoOverview(periodDays = 30): Promise<SeoOverviewResponse> {
  return authFetch<SeoOverviewResponse>(
    `/api/v1/seo/overview?period_days=${periodDays}`,
  );
}

export function getSeoOpportunities(periodDays = 30): Promise<SeoOpportunitiesResponse> {
  return authFetch<SeoOpportunitiesResponse>(
    `/api/v1/seo/opportunities?period_days=${periodDays}`,
  );
}

export function runSeoAudit(
  url: string,
  strategy: 'mobile' | 'desktop' = 'mobile',
): Promise<SeoAuditResponse> {
  return authFetch<SeoAuditResponse>('/api/v1/seo/audit', {
    method: 'POST',
    body: JSON.stringify({ url, strategy }),
  });
}

export function getSeoBacklinks(domain: string): Promise<SeoBacklinksResponse> {
  return authFetch<SeoBacklinksResponse>(
    `/api/v1/seo/backlinks?domain=${encodeURIComponent(domain)}`,
  );
}

export function getSeoKeywords(seed: string): Promise<SeoKeywordsResponse> {
  return authFetch<SeoKeywordsResponse>(
    `/api/v1/seo/keywords?seed=${encodeURIComponent(seed)}`,
  );
}
