import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { CreativeLens, CreativeRow, LensTotals } from '@/lib/marcom-api';

// ---------------------------------------------------------------------------
// Helper factories
// ---------------------------------------------------------------------------

function makeCreativeRow(overrides: Partial<CreativeRow> = {}): CreativeRow {
  return {
    ad_id: 'ad-001',
    ad_name: 'Yaz Kampanyası Banner',
    campaign_name: 'Yaz İndirimi 2026',
    channel: 'meta',
    impressions: 50000,
    clicks: 1500,
    ctr: 3.0,
    conversions: 120,
    traffic_share_pct: 22.5,
    insight: 'Bu kreatif tıklama oranında kampanyanın en iyisi.',
    ...overrides,
  };
}

function makeLens(overrides: Partial<CreativeLens> = {}): CreativeLens {
  return {
    period: { date_from: '2026-05-29', date_to: '2026-06-28' },
    totals: {
      impressions: 200000,
      clicks: 6000,
      ctr: 3.0,
      conversions: 480,
      creatives_count: 8,
    },
    headline: 'Yaz kampanyası kreatifleri beklentilerin üzerinde performans gösterdi.',
    top_creatives: [makeCreativeRow()],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('CreativeLens type', () => {
  it('accepts a full payload', () => {
    const lens: CreativeLens = makeLens();
    expect(lens.totals.impressions).toBe(200000);
    expect(lens.top_creatives).toHaveLength(1);
    expect(lens.period.date_from).toBe('2026-05-29');
  });

  it('top_creatives can be an empty array', () => {
    const lens: CreativeLens = makeLens({ top_creatives: [] });
    expect(lens.top_creatives).toHaveLength(0);
  });
});

describe('LensTotals type', () => {
  it('carries all required numeric fields', () => {
    const totals: LensTotals = {
      impressions: 100000,
      clicks: 3000,
      ctr: 3.0,
      conversions: 240,
      creatives_count: 5,
    };
    expect(totals.ctr).toBe(3.0);
    expect(totals.creatives_count).toBe(5);
  });
});

describe('CreativeRow type', () => {
  it('carries all required fields', () => {
    const row: CreativeRow = makeCreativeRow();
    expect(row.ad_id).toBe('ad-001');
    expect(row.ctr).toBe(3.0);
    expect(row.traffic_share_pct).toBe(22.5);
    expect(row.insight).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// getCreativeInsights — fetch mock
// ---------------------------------------------------------------------------

describe('getCreativeInsights', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: (_key: string) => 'test-token',
      removeItem: vi.fn(),
      setItem: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls GET /api/v1/marcom/creative-insights with no query string when no options given', async () => {
    const mockResponse = makeLens();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCreativeInsights } = await import('@/lib/marcom-api');
    const result = await getCreativeInsights();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/marcom/creative-insights');
    expect(url).not.toContain('?');
    expect(result.totals.impressions).toBe(200000);
    expect(result.top_creatives).toHaveLength(1);
  });

  it('appends date_from and date_to as query parameters when provided', async () => {
    const mockResponse = makeLens({
      period: { date_from: '2026-06-01', date_to: '2026-06-28' },
    });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCreativeInsights } = await import('@/lib/marcom-api');
    const result = await getCreativeInsights({
      date_from: '2026-06-01',
      date_to: '2026-06-28',
    });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).toContain('date_to=2026-06-28');
    expect(result.period.date_from).toBe('2026-06-01');
    expect(result.period.date_to).toBe('2026-06-28');
  });

  it('appends only date_from when date_to is omitted', async () => {
    const mockResponse = makeLens();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCreativeInsights } = await import('@/lib/marcom-api');
    await getCreativeInsights({ date_from: '2026-06-01' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).not.toContain('date_to=');
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse = makeLens();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCreativeInsights } = await import('@/lib/marcom-api');
    await getCreativeInsights();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('returns the parsed CreativeLens object including top_creatives fields', async () => {
    const row = makeCreativeRow({
      ad_id: 'ad-special',
      ad_name: 'Özel Kreatif',
      ctr: 5.7,
      traffic_share_pct: 41.2,
    });
    const mockResponse = makeLens({ top_creatives: [row] });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCreativeInsights } = await import('@/lib/marcom-api');
    const result = await getCreativeInsights();

    expect(result.top_creatives[0].ad_id).toBe('ad-special');
    expect(result.top_creatives[0].ad_name).toBe('Özel Kreatif');
    expect(result.top_creatives[0].ctr).toBe(5.7);
    expect(result.top_creatives[0].traffic_share_pct).toBe(41.2);
    expect(result.headline).toBeTruthy();
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCreativeInsights } = await import('@/lib/marcom-api');
    await expect(getCreativeInsights()).rejects.toThrow('Sunucu hatası');
  });

  it('throws with a fallback message when response text is empty on error', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve(''),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCreativeInsights } = await import('@/lib/marcom-api');
    await expect(getCreativeInsights()).rejects.toThrow('İstek başarısız');
  });
});
