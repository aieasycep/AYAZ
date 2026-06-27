// Feeds API — typed wrappers for /api/v1/feeds/*

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

export type SourceType = 'url_xml' | 'url_csv' | 'upload';

export type ChannelType =
  | 'google_shopping'
  | 'meta_catalog'
  | 'tiktok'
  | 'custom';

export type OutputFormat = 'xml' | 'csv' | 'json' | 'tsv';

export type RuleType =
  | 'set_value'
  | 'rename_field'
  | 'find_replace'
  | 'filter_include'
  | 'filter_exclude'
  | 'calculated';

export interface FeedSource {
  id: string;
  name: string;
  source_type: SourceType;
  source_url: string | null;
  item_count: number | null;
  last_synced: string | null; // ISO date — normalised from backend `last_synced_at`
  created_at: string;
}

export interface FeedChannel {
  id: string;
  // Backend field is `feed_source_id`; kept here for the FK. The list page does
  // not dereference this, so the rename is non-breaking.
  feed_source_id: string;
  name: string;
  channel_type: ChannelType;
  output_format: OutputFormat;
  public_token: string;
  is_active: boolean;
  created_at: string;
}

export interface FeedRule {
  id: string;
  /** Backend field name is feed_channel_id */
  feed_channel_id: string;
  position: number;
  rule_type: RuleType;
  config: Record<string, unknown>;
  is_paused: boolean;
  created_at: string;
}

// --- Normalisation ---
// Backend returns `last_synced_at`; the UI reads `last_synced`. Map it here.
function normaliseFeedSource(
  s: FeedSource & { last_synced_at?: string | null },
): FeedSource {
  if (s && s.last_synced == null && s.last_synced_at !== undefined) {
    s.last_synced = s.last_synced_at;
  }
  return s;
}

// --- Source API ---

export async function getFeedSources(): Promise<FeedSource[]> {
  const sources = await authFetch<FeedSource[]>('/api/v1/feeds/sources');
  return sources.map(normaliseFeedSource);
}

export interface CreateSourcePayload {
  name: string;
  source_type: SourceType;
  source_url: string;
}

export async function createFeedSource(
  payload: CreateSourcePayload,
): Promise<FeedSource> {
  return normaliseFeedSource(
    await authFetch<FeedSource>('/api/v1/feeds/sources', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  );
}

export async function syncFeedSource(id: string): Promise<FeedSource> {
  return normaliseFeedSource(
    await authFetch<FeedSource>(`/api/v1/feeds/sources/${id}/sync`, {
      method: 'POST',
    }),
  );
}

// --- Channel API ---

export function getFeedChannels(sourceId: string): Promise<FeedChannel[]> {
  return authFetch<FeedChannel[]>(`/api/v1/feeds/sources/${sourceId}/channels`);
}

export interface CreateChannelPayload {
  name: string;
  channel_type: ChannelType;
  output_format: OutputFormat;
}

export function createFeedChannel(
  sourceId: string,
  payload: CreateChannelPayload,
): Promise<FeedChannel> {
  return authFetch<FeedChannel>(`/api/v1/feeds/sources/${sourceId}/channels`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// --- Rule API ---

export function getChannelRules(channelId: string): Promise<FeedRule[]> {
  return authFetch<FeedRule[]>(`/api/v1/feeds/channels/${channelId}/rules`);
}

export interface CreateRulePayload {
  position: number;
  rule_type: RuleType;
  config: Record<string, unknown>;
}

export function createChannelRule(
  channelId: string,
  payload: CreateRulePayload,
): Promise<FeedRule> {
  return authFetch<FeedRule>(`/api/v1/feeds/channels/${channelId}/rules`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

// --- Rule update / delete ---

export interface PatchRulePayload {
  rule_type?: RuleType;
  position?: number;
  config?: Record<string, unknown>;
  is_paused?: boolean;
}

export function patchChannelRule(
  ruleId: string,
  payload: PatchRulePayload,
): Promise<FeedRule> {
  return authFetch<FeedRule>(`/api/v1/feeds/rules/${ruleId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function deleteChannelRule(ruleId: string): Promise<void> {
  return authFetch<void>(`/api/v1/feeds/rules/${ruleId}`, {
    method: 'DELETE',
  });
}

// --- Rule Studio: Impact ---

export interface RuleImpactStat {
  rule_id: string;
  position: number;
  rule_type: string;
  is_paused: boolean;
  affected_count: number;
  excluded_count: number;
}

export interface RulesImpactResponse {
  total_before: number;
  total_after: number;
  sampled: boolean;
  sampled_total: number | null;
  rules: RuleImpactStat[];
}

export function getRulesImpact(channelId: string): Promise<RulesImpactResponse> {
  return authFetch<RulesImpactResponse>(
    `/api/v1/feeds/channels/${channelId}/rules/impact`,
  );
}

// --- Rule Studio: Simulate ---

export interface SimulateRulePayload {
  rule_type: RuleType;
  config: Record<string, unknown>;
  position?: number;
}

export interface SimulateRuleResponse {
  affected_count: number;
  excluded_count: number;
  sample_before: Record<string, unknown>[];
  sample_after: Record<string, unknown>[];
}

export function simulateRule(
  channelId: string,
  payload: SimulateRulePayload,
): Promise<SimulateRuleResponse> {
  return authFetch<SimulateRuleResponse>(
    `/api/v1/feeds/channels/${channelId}/rules/simulate`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

// --- Rule Studio: Lint ---

export interface LintIssue {
  severity: string; // 'error' | 'warning' | 'info'
  rule_id: string;
  position: number;
  code: string; // 'no_effect' | 'excludes_all' | 'shadowed' | 'duplicate'
  message: string;
}

export interface LintResponse {
  issues: LintIssue[];
}

export function lintChannelRules(channelId: string): Promise<LintResponse> {
  return authFetch<LintResponse>(
    `/api/v1/feeds/channels/${channelId}/rules/lint`,
  );
}

// --- Rule from natural-language text ---

export interface RuleFromTextResponse {
  rule_type: RuleType;
  config: Record<string, unknown>;
  explanation: string;
  confidence: 'high' | 'low';
  impact?: {
    affected_count: number;
    excluded_count: number;
  };
}

export function ruleFromText(
  channelId: string,
  text: string,
): Promise<RuleFromTextResponse> {
  return authFetch<RuleFromTextResponse>(
    `/api/v1/feeds/channels/${channelId}/rules/from-text`,
    { method: 'POST', body: JSON.stringify({ text }) },
  );
}

// --- Public feed URL helper ---

export function getPublicFeedUrl(publicToken: string): string {
  return `${API_BASE}/api/v1/feeds/public/${publicToken}`;
}

// --- AI Product Enrichment ---

export type EnrichableField = 'color' | 'brand' | 'category' | 'material' | 'title';

export interface EnrichSourcePayload {
  fields: EnrichableField[];
  product_ids?: string[];
  limit?: number;
}

export interface EnrichmentSuggestion {
  product_id: string;
  field: EnrichableField;
  current: string | null;
  suggested: string;
  confidence: 'high' | 'low';
  source: 'ai' | 'heuristic';
}

export interface EnrichSourceResponse {
  suggestions: EnrichmentSuggestion[];
  sampled: boolean;
  sampled_total: number | null;
}

export function enrichSource(
  sourceId: string,
  payload: EnrichSourcePayload,
): Promise<EnrichSourceResponse> {
  return authFetch<EnrichSourceResponse>(
    `/api/v1/feeds/sources/${sourceId}/enrich`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export interface EnrichmentApproval {
  product_id: string;
  field: EnrichableField;
  value: string;
}

export interface ApplyEnrichmentPayload {
  approvals: EnrichmentApproval[];
}

export interface ApplyEnrichmentResponse {
  applied_count: number;
}

export function applyEnrichment(
  sourceId: string,
  payload: ApplyEnrichmentPayload,
): Promise<ApplyEnrichmentResponse> {
  return authFetch<ApplyEnrichmentResponse>(
    `/api/v1/feeds/sources/${sourceId}/enrich/apply`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

// --- Feed Quality ---

export interface QualityIssue {
  code: string; // missing_required_field | missing_recommended_field | duplicate_id | invalid_price | title_too_long | missing_image
  severity: 'error' | 'warning';
  field: string;
  message: string; // Turkish
  affected_count: number;
  sample_ids: string[];
}

export interface FeedQualityResponse {
  score: number; // 0–100
  total: number;
  valid: number;
  sampled?: boolean;
  issues: QualityIssue[];
}

export function getChannelQuality(channelId: string): Promise<FeedQualityResponse> {
  return authFetch<FeedQualityResponse>(
    `/api/v1/feeds/channels/${channelId}/quality`,
  );
}
