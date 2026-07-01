import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  Recommendation,
  RecommendationFeed,
  RecommendationSummary,
  WeeklyStrategy,
  FocusArea,
  RecommendationActionResult,
  RecommendationActionRequest,
} from '@/lib/recommendations-api';
import {
  IMPACT_LABELS,
  EFFORT_LABELS,
  STATUS_LABELS,
  CATEGORY_LABELS,
} from '@/lib/recommendations-api';

// ---------------------------------------------------------------------------
// Label maps
// ---------------------------------------------------------------------------

describe('IMPACT_LABELS', () => {
  it('maps all impact values to Turkish labels', () => {
    expect(IMPACT_LABELS.high).toBe('Yüksek etki');
    expect(IMPACT_LABELS.medium).toBe('Orta etki');
    expect(IMPACT_LABELS.low).toBe('Düşük etki');
  });
});

describe('EFFORT_LABELS', () => {
  it('maps all effort values to Turkish labels', () => {
    expect(EFFORT_LABELS.low).toBe('Düşük çaba');
    expect(EFFORT_LABELS.medium).toBe('Orta çaba');
    expect(EFFORT_LABELS.high).toBe('Yüksek çaba');
  });
});

describe('STATUS_LABELS', () => {
  it('maps all status values to Turkish labels', () => {
    expect(STATUS_LABELS.open).toBe('Açık');
    expect(STATUS_LABELS.accepted).toBe('Kabul edildi');
    expect(STATUS_LABELS.snoozed).toBe('Ertelendi');
    expect(STATUS_LABELS.dismissed).toBe('Reddedildi');
  });
});

describe('CATEGORY_LABELS', () => {
  it('maps all category values to Turkish labels', () => {
    expect(CATEGORY_LABELS.budget).toBe('Bütçe');
    expect(CATEGORY_LABELS.performance).toBe('Performans');
    expect(CATEGORY_LABELS.tracking).toBe('Ölçümleme');
    expect(CATEGORY_LABELS.content).toBe('İçerik');
    expect(CATEGORY_LABELS.inbox).toBe('Gelen Kutusu');
    expect(CATEGORY_LABELS.goal).toBe('Hedef');
    expect(CATEGORY_LABELS.audit).toBe('Denetim');
    expect(CATEGORY_LABELS.benchmark).toBe('Kıyaslama');
  });
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeRecommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    key: 'budget:overspend',
    category: 'budget',
    category_label: 'Bütçe',
    title: 'Meta bütçesi planın önünde',
    rationale: 'Meta kanalında ayın %60\'ında planın %78\'i harcandı; ay sonunda %18 aşım riski var.',
    impact: 'high',
    impact_label: 'Yüksek etki',
    effort: 'low',
    effort_label: 'Düşük çaba',
    metric: { label: 'Tempo', value: '%118' },
    action_label: 'Bütçe planını aç',
    action_href: '/planning',
    status: 'open',
    snoozed_until: null,
    ...overrides,
  };
}

function makeSummary(overrides: Partial<RecommendationSummary> = {}): RecommendationSummary {
  return {
    open: 7,
    accepted: 1,
    snoozed: 1,
    dismissed: 0,
    total: 9,
    high_impact_open: 3,
    ...overrides,
  };
}

function makeFeed(overrides: Partial<RecommendationFeed> = {}): RecommendationFeed {
  return {
    generated_at: '2026-06-28T10:00:00Z',
    summary: makeSummary(),
    recommendations: [makeRecommendation()],
    ...overrides,
  };
}

function makeFocusArea(overrides: Partial<FocusArea> = {}): FocusArea {
  return {
    title: 'Bütçe disiplini',
    detail: 'Meta harcamasını günlük kontrol edin.',
    ...overrides,
  };
}

function makeWeeklyStrategy(overrides: Partial<WeeklyStrategy> = {}): WeeklyStrategy {
  return {
    week_label: '22–28 Haziran 2026',
    headline: 'Bu hafta ROAS\'ı korurken Meta aşımını düzeltin.',
    narrative: 'Bu hafta odaklanmanız gereken birkaç kritik alan var. Meta bütçe aşımı öncelikli eylem gerektirir.',
    focus_areas: [
      makeFocusArea(),
      makeFocusArea({ title: 'ROAS koruması', detail: 'Dönüşüm odaklı kampanyalara odaklanın.' }),
    ],
    top_recommendations: [makeRecommendation()],
    source: 'template',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Shared mock setup
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// getRecommendationFeed
// ---------------------------------------------------------------------------

describe('getRecommendationFeed', () => {
  beforeEach(() => {
    setupLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/recommendations/feed', async () => {
    const mockFeed = makeFeed();
    vi.stubGlobal('fetch', makeFetchMock(mockFeed));

    const { getRecommendationFeed } = await import('@/lib/recommendations-api');
    const result = await getRecommendationFeed();

    const fetchMock = vi.mocked(global.fetch);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/recommendations/feed');
  });

  it('parses feed with summary and recommendations', async () => {
    const mockFeed = makeFeed();
    vi.stubGlobal('fetch', makeFetchMock(mockFeed));

    const { getRecommendationFeed } = await import('@/lib/recommendations-api');
    const result = await getRecommendationFeed();

    expect(result.generated_at).toBe('2026-06-28T10:00:00Z');
    expect(result.summary.open).toBe(7);
    expect(result.summary.total).toBe(9);
    expect(result.summary.high_impact_open).toBe(3);
    expect(result.recommendations).toHaveLength(1);
    expect(result.recommendations[0].key).toBe('budget:overspend');
    expect(result.recommendations[0].category).toBe('budget');
    expect(result.recommendations[0].impact).toBe('high');
    expect(result.recommendations[0].status).toBe('open');
  });

  it('parses a recommendation with a metric', async () => {
    const mockFeed = makeFeed();
    vi.stubGlobal('fetch', makeFetchMock(mockFeed));

    const { getRecommendationFeed } = await import('@/lib/recommendations-api');
    const result = await getRecommendationFeed();

    const rec = result.recommendations[0];
    expect(rec.metric).not.toBeNull();
    expect(rec.metric!.label).toBe('Tempo');
    expect(rec.metric!.value).toBe('%118');
  });

  it('parses a recommendation with null metric', async () => {
    const mockFeed = makeFeed({
      recommendations: [makeRecommendation({ metric: null })],
    });
    vi.stubGlobal('fetch', makeFetchMock(mockFeed));

    const { getRecommendationFeed } = await import('@/lib/recommendations-api');
    const result = await getRecommendationFeed();

    expect(result.recommendations[0].metric).toBeNull();
  });

  it('sends the Bearer token in the Authorization header', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeFeed()));

    const { getRecommendationFeed } = await import('@/lib/recommendations-api');
    await getRecommendationFeed();

    const fetchMock = vi.mocked(global.fetch);
    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('throws when the server returns a non-ok status', async () => {
    vi.stubGlobal('fetch', makeErrorFetchMock(500, 'Sunucu hatası'));

    const { getRecommendationFeed } = await import('@/lib/recommendations-api');
    await expect(getRecommendationFeed()).rejects.toThrow('Sunucu hatası');
  });
});

// ---------------------------------------------------------------------------
// getWeeklyStrategy
// ---------------------------------------------------------------------------

describe('getWeeklyStrategy', () => {
  beforeEach(() => {
    setupLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/recommendations/weekly-strategy', async () => {
    vi.stubGlobal('fetch', makeFetchMock(makeWeeklyStrategy()));

    const { getWeeklyStrategy } = await import('@/lib/recommendations-api');
    await getWeeklyStrategy();

    const fetchMock = vi.mocked(global.fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/recommendations/weekly-strategy');
  });

  it('parses strategy with week_label, headline, and narrative', async () => {
    const mockStrategy = makeWeeklyStrategy();
    vi.stubGlobal('fetch', makeFetchMock(mockStrategy));

    const { getWeeklyStrategy } = await import('@/lib/recommendations-api');
    const result = await getWeeklyStrategy();

    expect(result.week_label).toBe('22–28 Haziran 2026');
    expect(result.headline).toBe('Bu hafta ROAS\'ı korurken Meta aşımını düzeltin.');
    expect(result.narrative).toContain('Meta bütçe aşımı');
  });

  it('parses focus_areas', async () => {
    const mockStrategy = makeWeeklyStrategy();
    vi.stubGlobal('fetch', makeFetchMock(mockStrategy));

    const { getWeeklyStrategy } = await import('@/lib/recommendations-api');
    const result = await getWeeklyStrategy();

    expect(result.focus_areas).toHaveLength(2);
    expect(result.focus_areas[0].title).toBe('Bütçe disiplini');
    expect(result.focus_areas[1].title).toBe('ROAS koruması');
  });

  it('parses top_recommendations', async () => {
    const mockStrategy = makeWeeklyStrategy();
    vi.stubGlobal('fetch', makeFetchMock(mockStrategy));

    const { getWeeklyStrategy } = await import('@/lib/recommendations-api');
    const result = await getWeeklyStrategy();

    expect(result.top_recommendations).toHaveLength(1);
    expect(result.top_recommendations[0].key).toBe('budget:overspend');
  });

  it('parses source field (template)', async () => {
    const mockStrategy = makeWeeklyStrategy({ source: 'template' });
    vi.stubGlobal('fetch', makeFetchMock(mockStrategy));

    const { getWeeklyStrategy } = await import('@/lib/recommendations-api');
    const result = await getWeeklyStrategy();

    expect(result.source).toBe('template');
  });

  it('parses source field (ai)', async () => {
    const mockStrategy = makeWeeklyStrategy({ source: 'ai' });
    vi.stubGlobal('fetch', makeFetchMock(mockStrategy));

    const { getWeeklyStrategy } = await import('@/lib/recommendations-api');
    const result = await getWeeklyStrategy();

    expect(result.source).toBe('ai');
  });

  it('throws when the server returns a non-ok status', async () => {
    vi.stubGlobal('fetch', makeErrorFetchMock(503, 'Servis kullanılamıyor'));

    const { getWeeklyStrategy } = await import('@/lib/recommendations-api');
    await expect(getWeeklyStrategy()).rejects.toThrow('Servis kullanılamıyor');
  });
});

// ---------------------------------------------------------------------------
// applyRecommendationAction
// ---------------------------------------------------------------------------

describe('applyRecommendationAction', () => {
  beforeEach(() => {
    setupLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('POSTs to URL-encoded key path for plain key', async () => {
    const mockResult: RecommendationActionResult = {
      key: 'budget:overspend',
      status: 'accepted',
      snoozed_until: null,
      note: null,
    };
    vi.stubGlobal('fetch', makeFetchMock(mockResult));

    const { applyRecommendationAction } = await import('@/lib/recommendations-api');
    await applyRecommendationAction('budget:overspend', { action: 'accept' });

    const fetchMock = vi.mocked(global.fetch);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    // The colon in "budget:overspend" must be URL-encoded
    expect(url).toContain('/api/v1/recommendations/budget%3Aoverspend/action');
  });

  it('POSTs with correct action body', async () => {
    const mockResult: RecommendationActionResult = {
      key: 'budget:overspend',
      status: 'accepted',
      snoozed_until: null,
      note: null,
    };
    vi.stubGlobal('fetch', makeFetchMock(mockResult));

    const req: RecommendationActionRequest = { action: 'accept' };
    const { applyRecommendationAction } = await import('@/lib/recommendations-api');
    await applyRecommendationAction('budget:overspend', req);

    const fetchMock = vi.mocked(global.fetch);
    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.action).toBe('accept');
  });

  it('POSTs snooze action with snooze_days in body', async () => {
    const mockResult: RecommendationActionResult = {
      key: 'performance:low-ctr',
      status: 'snoozed',
      snoozed_until: '2026-07-05T00:00:00Z',
      note: null,
    };
    vi.stubGlobal('fetch', makeFetchMock(mockResult));

    const req: RecommendationActionRequest = { action: 'snooze', snooze_days: 7 };
    const { applyRecommendationAction } = await import('@/lib/recommendations-api');
    await applyRecommendationAction('performance:low-ctr', req);

    const fetchMock = vi.mocked(global.fetch);
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('performance%3Alow-ctr');
    const body = JSON.parse(opts.body as string);
    expect(body.action).toBe('snooze');
    expect(body.snooze_days).toBe(7);
  });

  it('parses the action result with snoozed_until', async () => {
    const mockResult: RecommendationActionResult = {
      key: 'budget:overspend',
      status: 'snoozed',
      snoozed_until: '2026-07-05T00:00:00Z',
      note: null,
    };
    vi.stubGlobal('fetch', makeFetchMock(mockResult));

    const { applyRecommendationAction } = await import('@/lib/recommendations-api');
    const result = await applyRecommendationAction('budget:overspend', {
      action: 'snooze',
      snooze_days: 7,
    });

    expect(result.status).toBe('snoozed');
    expect(result.snoozed_until).toBe('2026-07-05T00:00:00Z');
    expect(result.note).toBeNull();
  });

  it('parses the action result for dismiss', async () => {
    const mockResult: RecommendationActionResult = {
      key: 'content:missing-alt',
      status: 'dismissed',
      snoozed_until: null,
      note: null,
    };
    vi.stubGlobal('fetch', makeFetchMock(mockResult));

    const { applyRecommendationAction } = await import('@/lib/recommendations-api');
    const result = await applyRecommendationAction('content:missing-alt', {
      action: 'dismiss',
    });

    expect(result.key).toBe('content:missing-alt');
    expect(result.status).toBe('dismissed');
  });

  it('parses the action result for reopen', async () => {
    const mockResult: RecommendationActionResult = {
      key: 'goal:behind',
      status: 'open',
      snoozed_until: null,
      note: null,
    };
    vi.stubGlobal('fetch', makeFetchMock(mockResult));

    const { applyRecommendationAction } = await import('@/lib/recommendations-api');
    const result = await applyRecommendationAction('goal:behind', {
      action: 'reopen',
    });

    expect(result.status).toBe('open');
  });

  it('throws when the server returns a non-ok status', async () => {
    vi.stubGlobal('fetch', makeErrorFetchMock(404, 'Öneri bulunamadı'));

    const { applyRecommendationAction } = await import('@/lib/recommendations-api');
    await expect(
      applyRecommendationAction('budget:overspend', { action: 'accept' }),
    ).rejects.toThrow('Öneri bulunamadı');
  });
});
