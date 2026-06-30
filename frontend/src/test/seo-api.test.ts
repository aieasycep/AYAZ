/**
 * seo-api.ts — unit tests for the SEO API client.
 *
 * Mocks global.fetch + localStorage; tests each exported function for:
 *  - correct URL and method
 *  - Bearer token header
 *  - shape of returned data
 *  - error propagation
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  SeoOverviewResponse,
  SeoOpportunitiesResponse,
  SeoAuditResponse,
  SeoBacklinksResponse,
  SeoKeywordsResponse,
} from '@/lib/seo-api';
import {
  OPPORTUNITY_TYPE_LABELS,
  SEVERITY_LABELS,
} from '@/lib/seo-api';

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeOverview(): SeoOverviewResponse {
  return {
    period_days: 30,
    current: { clicks: 1200, impressions: 45000, ctr: 0.0267, avg_position: 12.4 },
    prior: { clicks: 1000, impressions: 40000, ctr: 0.025, avg_position: 14.2 },
    trends: {
      clicks_delta_pct: 20.0,
      impressions_delta_pct: 12.5,
      ctr_delta_pct: 6.8,
      position_delta_pct: -12.7,
    },
    top_queries: [
      { query: 'dijital pazarlama', clicks: 120, impressions: 3000, ctr: 0.04, avg_position: 5.1 },
    ],
    top_pages: [
      { page: 'https://example.com/blog', clicks: 300, impressions: 8000, ctr: 0.0375, avg_position: 6.2 },
    ],
  };
}

function makeOpportunities(): SeoOpportunitiesResponse {
  return {
    opportunities: [
      {
        type: 'striking_distance',
        severity: 'warning',
        title: "'seo araçları' sorgusu 9.2. sırada",
        body: 'İçeriği optimize ederek ilk sayfaya taşıyabilirsiniz.',
        data: { query: 'seo araçları', avg_position: 9.2, impressions: 500, clicks: 10, ctr: 0.02 },
      },
      {
        type: 'low_ctr',
        severity: 'warning',
        title: "'içerik yönetimi' yüksek gösterim, düşük tıklama",
        body: 'Meta açıklamasını iyileştirin.',
        data: { query: 'içerik yönetimi', ctr: 0.01, impressions: 1200, avg_position: 3.1 },
      },
    ],
    count: 2,
    emitted: null,
  };
}

function makeAuditOk(): SeoAuditResponse {
  return {
    status: 'ok',
    url: 'https://example.com/',
    strategy: 'mobile',
    core_web_vitals: {
      lcp: { value: 2.4, unit: 's', score: 85 },
      cls: { value: 0.05, unit: '', score: 90 },
      fcp: { value: 1.2, unit: 's', score: 88 },
      ttfb: { value: 0.4, unit: 's', score: 92 },
    },
    lighthouse_scores: {
      performance: 78,
      seo: 95,
      accessibility: 82,
      best_practices: 88,
    },
    issues: [
      { id: 'render-blocking-resources', title: 'Render-blocking resources', score: 45 },
    ],
  };
}

function makeAuditPending(): SeoAuditResponse {
  return { status: 'kimlik_bekliyor', message: 'API anahtarı eksik.' };
}

function makeBacklinksConnectRequired(): SeoBacklinksResponse {
  return {
    status: 'connect_required',
    message: 'DataForSEO entegrasyonu bağlı değil.',
    integration_key: 'dataforseo',
  };
}

function makeKeywordsConnectRequired(): SeoKeywordsResponse {
  return {
    status: 'connect_required',
    message: 'DataForSEO entegrasyonu bağlı değil.',
    integration_key: 'dataforseo',
  };
}

// ── Mock helpers ──────────────────────────────────────────────────────────────

function setupLocalStorage() {
  vi.stubGlobal('localStorage', {
    getItem: (_key: string) => 'test-token',
    removeItem: vi.fn(),
    setItem: vi.fn(),
  });
}

function makeFetchMock(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

function makeErrorFetchMock(status: number, message: string) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    text: () => Promise.resolve(message),
  });
}

// ── Label map tests ───────────────────────────────────────────────────────────

describe('OPPORTUNITY_TYPE_LABELS', () => {
  it('maps striking_distance to Turkish', () => {
    expect(OPPORTUNITY_TYPE_LABELS.striking_distance).toBe('Sıçrama mesafesi');
  });

  it('maps low_ctr to Turkish', () => {
    expect(OPPORTUNITY_TYPE_LABELS.low_ctr).toBe('Yüksek gösterim · düşük CTR');
  });

  it('maps cannibalization to Turkish', () => {
    expect(OPPORTUNITY_TYPE_LABELS.cannibalization).toBe('İçerik yamyamlığı');
  });

  it('maps top_movers to Turkish', () => {
    expect(OPPORTUNITY_TYPE_LABELS.top_movers).toBe('En çok değişenler');
  });
});

describe('SEVERITY_LABELS', () => {
  it('maps all severity values to Turkish', () => {
    expect(SEVERITY_LABELS.critical).toBe('Kritik');
    expect(SEVERITY_LABELS.warning).toBe('Uyarı');
    expect(SEVERITY_LABELS.info).toBe('Bilgi');
  });
});

// ── getSeoOverview ────────────────────────────────────────────────────────────

describe('getSeoOverview', () => {
  beforeEach(() => {
    setupLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/seo/overview with default period_days=30', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOverview()));

    const { getSeoOverview } = await import('@/lib/seo-api');
    await getSeoOverview();

    const fetchMock = vi.mocked(global.fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/seo/overview');
    expect(url).toContain('period_days=30');
  });

  it('GETs with custom period_days', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOverview()));

    const { getSeoOverview } = await import('@/lib/seo-api');
    await getSeoOverview(90);

    const fetchMock = vi.mocked(global.fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('period_days=90');
  });

  it('sends Bearer token', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOverview()));

    const { getSeoOverview } = await import('@/lib/seo-api');
    await getSeoOverview();

    const fetchMock = vi.mocked(global.fetch);
    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
  });

  it('parses current period totals', async () => {
    const mock = makeOverview();
    vi.stubGlobal('fetch', makeFetchMock(mock));

    const { getSeoOverview } = await import('@/lib/seo-api');
    const result = await getSeoOverview();

    expect(result.current.clicks).toBe(1200);
    expect(result.current.impressions).toBe(45000);
    expect(result.current.ctr).toBeCloseTo(0.0267);
    expect(result.current.avg_position).toBeCloseTo(12.4);
  });

  it('parses trends deltas', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOverview()));

    const { getSeoOverview } = await import('@/lib/seo-api');
    const result = await getSeoOverview();

    expect(result.trends.clicks_delta_pct).toBe(20.0);
    expect(result.trends.position_delta_pct).toBe(-12.7);
  });

  it('parses top_queries', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOverview()));

    const { getSeoOverview } = await import('@/lib/seo-api');
    const result = await getSeoOverview();

    expect(result.top_queries).toHaveLength(1);
    expect(result.top_queries[0].query).toBe('dijital pazarlama');
    expect(result.top_queries[0].clicks).toBe(120);
  });

  it('parses top_pages', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOverview()));

    const { getSeoOverview } = await import('@/lib/seo-api');
    const result = await getSeoOverview();

    expect(result.top_pages).toHaveLength(1);
    expect(result.top_pages[0].page).toBe('https://example.com/blog');
  });

  it('handles null trend deltas gracefully', async () => {
    const mock = makeOverview();
    mock.trends.clicks_delta_pct = null;
    vi.stubGlobal('fetch', makeFetchMock(mock));

    const { getSeoOverview } = await import('@/lib/seo-api');
    const result = await getSeoOverview();

    expect(result.trends.clicks_delta_pct).toBeNull();
  });

  it('throws on non-ok status', async () => {
    vi.stubGlobal('fetch', makeErrorFetchMock(500, 'Sunucu hatası'));

    const { getSeoOverview } = await import('@/lib/seo-api');
    await expect(getSeoOverview()).rejects.toThrow('Sunucu hatası');
  });
});

// ── getSeoOpportunities ───────────────────────────────────────────────────────

describe('getSeoOpportunities', () => {
  beforeEach(() => {
    setupLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/seo/opportunities', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOpportunities()));

    const { getSeoOpportunities } = await import('@/lib/seo-api');
    await getSeoOpportunities();

    const fetchMock = vi.mocked(global.fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/seo/opportunities');
    expect(url).toContain('period_days=30');
  });

  it('parses opportunity list with type and severity', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOpportunities()));

    const { getSeoOpportunities } = await import('@/lib/seo-api');
    const result = await getSeoOpportunities();

    expect(result.count).toBe(2);
    expect(result.opportunities[0].type).toBe('striking_distance');
    expect(result.opportunities[0].severity).toBe('warning');
    expect(result.opportunities[1].type).toBe('low_ctr');
  });

  it('parses opportunity data field', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOpportunities()));

    const { getSeoOpportunities } = await import('@/lib/seo-api');
    const result = await getSeoOpportunities();

    const first = result.opportunities[0];
    expect((first.data as Record<string, unknown>).avg_position).toBe(9.2);
  });

  it('emitted is null when not requested', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeOpportunities()));

    const { getSeoOpportunities } = await import('@/lib/seo-api');
    const result = await getSeoOpportunities();

    expect(result.emitted).toBeNull();
  });

  it('throws on non-ok status', async () => {
    vi.stubGlobal('fetch', makeErrorFetchMock(503, 'Servis kullanılamıyor'));

    const { getSeoOpportunities } = await import('@/lib/seo-api');
    await expect(getSeoOpportunities()).rejects.toThrow('Servis kullanılamıyor');
  });
});

// ── runSeoAudit ───────────────────────────────────────────────────────────────

describe('runSeoAudit', () => {
  beforeEach(() => {
    setupLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('POSTs to /api/v1/seo/audit', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeAuditOk()));

    const { runSeoAudit } = await import('@/lib/seo-api');
    await runSeoAudit('https://example.com/');

    const fetchMock = vi.mocked(global.fetch);
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/seo/audit');
    expect(opts.method).toBe('POST');
  });

  it('sends url and strategy in body', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeAuditOk()));

    const { runSeoAudit } = await import('@/lib/seo-api');
    await runSeoAudit('https://example.com/', 'desktop');

    const fetchMock = vi.mocked(global.fetch);
    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.url).toBe('https://example.com/');
    expect(body.strategy).toBe('desktop');
  });

  it('defaults strategy to mobile', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeAuditOk()));

    const { runSeoAudit } = await import('@/lib/seo-api');
    await runSeoAudit('https://example.com/');

    const fetchMock = vi.mocked(global.fetch);
    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.strategy).toBe('mobile');
  });

  it('parses ok audit with core_web_vitals', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeAuditOk()));

    const { runSeoAudit } = await import('@/lib/seo-api');
    const result = await runSeoAudit('https://example.com/');

    expect(result.status).toBe('ok');
    expect(result.core_web_vitals?.lcp.value).toBe(2.4);
    expect(result.core_web_vitals?.cls.score).toBe(90);
    expect(result.lighthouse_scores?.performance).toBe(78);
    expect(result.lighthouse_scores?.seo).toBe(95);
  });

  it('parses kimlik_bekliyor status gracefully', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeAuditPending()));

    const { runSeoAudit } = await import('@/lib/seo-api');
    const result = await runSeoAudit('https://example.com/');

    expect(result.status).toBe('kimlik_bekliyor');
    expect(result.message).toBe('API anahtarı eksik.');
  });

  it('parses issues list', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeAuditOk()));

    const { runSeoAudit } = await import('@/lib/seo-api');
    const result = await runSeoAudit('https://example.com/');

    expect(result.issues).toHaveLength(1);
    expect(result.issues![0].id).toBe('render-blocking-resources');
    expect(result.issues![0].score).toBe(45);
  });

  it('throws on non-ok HTTP status', async () => {
    vi.stubGlobal('fetch', makeErrorFetchMock(422, 'URL geçersiz'));

    const { runSeoAudit } = await import('@/lib/seo-api');
    await expect(runSeoAudit('not-a-url')).rejects.toThrow('URL geçersiz');
  });
});

// ── getSeoBacklinks ───────────────────────────────────────────────────────────

describe('getSeoBacklinks', () => {
  beforeEach(() => {
    setupLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/seo/backlinks with encoded domain', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeBacklinksConnectRequired()));

    const { getSeoBacklinks } = await import('@/lib/seo-api');
    await getSeoBacklinks('example.com');

    const fetchMock = vi.mocked(global.fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/seo/backlinks');
    expect(url).toContain('domain=example.com');
  });

  it('returns connect_required when DataForSEO not connected', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeBacklinksConnectRequired()));

    const { getSeoBacklinks } = await import('@/lib/seo-api');
    const result = await getSeoBacklinks('example.com');

    expect(result.status).toBe('connect_required');
    expect((result as { integration_key: string }).integration_key).toBe('dataforseo');
  });

  it('URL-encodes domain with special chars', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeBacklinksConnectRequired()));

    const { getSeoBacklinks } = await import('@/lib/seo-api');
    await getSeoBacklinks('sub.example.com/path');

    const fetchMock = vi.mocked(global.fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('domain=sub.example.com%2Fpath');
  });
});

// ── getSeoKeywords ────────────────────────────────────────────────────────────

describe('getSeoKeywords', () => {
  beforeEach(() => {
    setupLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/seo/keywords with encoded seed', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeKeywordsConnectRequired()));

    const { getSeoKeywords } = await import('@/lib/seo-api');
    await getSeoKeywords('dijital pazarlama');

    const fetchMock = vi.mocked(global.fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/seo/keywords');
    expect(url).toContain('seed=dijital%20pazarlama');
  });

  it('returns connect_required when DataForSEO not connected', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeKeywordsConnectRequired()));

    const { getSeoKeywords } = await import('@/lib/seo-api');
    const result = await getSeoKeywords('test');

    expect(result.status).toBe('connect_required');
  });

  it('throws on non-ok HTTP status', async () => {
    vi.stubGlobal('fetch', makeErrorFetchMock(500, 'Sunucu hatası'));

    const { getSeoKeywords } = await import('@/lib/seo-api');
    await expect(getSeoKeywords('test')).rejects.toThrow('Sunucu hatası');
  });
});
