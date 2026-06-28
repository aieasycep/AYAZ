import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  SimBaseline,
  SimBaselineChannel,
  SimResult,
  SimChannel,
  SimTotals,
  SimDeltas,
} from '@/lib/budget-simulator-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeBaselineChannel(overrides?: Partial<SimBaselineChannel>): SimBaselineChannel {
  return {
    key: 'meta_ads',
    label: 'Meta Ads',
    spend: 180000,
    impressions: 5000000,
    clicks: 120000,
    conversions: 2400,
    conversion_value: 660000,
    cpc: 1.5,
    cpm: 36,
    cvr: 2.0,
    roas: 3.67,
    aov: 275,
    cpa: 75,
    spend_share_pct: 39.8,
    ...overrides,
  };
}

function makeTotals(overrides?: Partial<SimTotals>): SimTotals {
  return {
    spend: 452149,
    impressions: 12000000,
    clicks: 300000,
    conversions: 6000,
    conversion_value: 1500000,
    roas: 3.31,
    cpc: 1.51,
    cvr: 2.0,
    cpa: 75,
    ...overrides,
  };
}

function makeMockBaseline(): SimBaseline {
  return {
    lookback_days: 30,
    period: { date_from: '2026-05-27', date_to: '2026-06-25' },
    total_spend: 452149,
    channels: [makeBaselineChannel()],
    totals: makeTotals(),
  };
}

function makeSimChannel(overrides?: Partial<SimChannel>): SimChannel {
  return {
    key: 'meta_ads',
    label: 'Meta Ads',
    spend: 200000,
    impressions: 5500000,
    clicks: 130000,
    conversions: 2600,
    conversion_value: 715000,
    roas: 3.575,
    cpa: 76.92,
    baseline_spend: 180000,
    spend_delta: 20000,
    spend_delta_pct: 11.11,
    ...overrides,
  };
}

function makeDeltas(overrides?: Partial<SimDeltas>): SimDeltas {
  return {
    impressions_pct: 5.2,
    clicks_pct: 4.8,
    conversions_pct: 3.1,
    conversion_value_pct: 3.1,
    roas_pct: -1.2,
    ...overrides,
  };
}

function makeMockSimResult(): SimResult {
  return {
    lookback_days: 30,
    total_spend: 400000,
    channels: [makeSimChannel()],
    projected_totals: makeTotals({ spend: 400000 }),
    baseline_totals: makeTotals(),
    deltas: makeDeltas(),
    assumptions: [
      'Son 30 günlük kanal verimliliği baz alınmıştır.',
      'Dönüşüm oranları sabit kabul edilmiştir.',
    ],
  };
}

function stubLocalStorage(token = 'test-token') {
  vi.stubGlobal('localStorage', {
    getItem: (_key: string) => token,
    removeItem: vi.fn(),
    setItem: vi.fn(),
  });
}

function makeFetchMock<T>(body: T) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

// ---------------------------------------------------------------------------
// getBaseline
// ---------------------------------------------------------------------------

describe('getBaseline', () => {
  beforeEach(() => {
    stubLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/budget-simulator/baseline with no query string when lookbackDays is omitted', async () => {
    const mockResponse = makeMockBaseline();
    const fetchMock = makeFetchMock(mockResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { getBaseline } = await import('@/lib/budget-simulator-api');
    const result = await getBaseline();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/budget-simulator/baseline');
    expect(url).not.toContain('?');
    expect(result.lookback_days).toBe(30);
    expect(result.channels).toHaveLength(1);
    expect(result.channels[0].key).toBe('meta_ads');
  });

  it('appends ?lookback_days when a value is given', async () => {
    const mockResponse = makeMockBaseline();
    const fetchMock = makeFetchMock(mockResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { getBaseline } = await import('@/lib/budget-simulator-api');
    await getBaseline(60);

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('lookback_days=60');
  });

  it('sends Bearer token in Authorization header', async () => {
    const mockResponse = makeMockBaseline();
    const fetchMock = makeFetchMock(mockResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { getBaseline } = await import('@/lib/budget-simulator-api');
    await getBaseline();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('parses channels, period, and totals from the response', async () => {
    const mockResponse = makeMockBaseline();
    const fetchMock = makeFetchMock(mockResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { getBaseline } = await import('@/lib/budget-simulator-api');
    const result = await getBaseline();

    expect(result.period.date_from).toBe('2026-05-27');
    expect(result.period.date_to).toBe('2026-06-25');
    expect(result.total_spend).toBe(452149);
    expect(result.totals.roas).toBe(3.31);
    expect(result.channels[0].spend_share_pct).toBe(39.8);
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBaseline } = await import('@/lib/budget-simulator-api');
    await expect(getBaseline()).rejects.toThrow('Sunucu hatası');
  });

  it('throws "Oturum süresi doldu" on 401', async () => {
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: {
          getItem: () => 'test-token',
          removeItem: vi.fn(),
          setItem: vi.fn(),
        },
        location: { href: '' },
      },
      writable: true,
      configurable: true,
    });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBaseline } = await import('@/lib/budget-simulator-api');
    await expect(getBaseline()).rejects.toThrow('Oturum süresi doldu');
  });
});

// ---------------------------------------------------------------------------
// simulate
// ---------------------------------------------------------------------------

describe('simulate', () => {
  beforeEach(() => {
    stubLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('POSTs to /api/v1/budget-simulator/simulate with allocations in the body', async () => {
    const mockResponse = makeMockSimResult();
    const fetchMock = makeFetchMock(mockResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { simulate } = await import('@/lib/budget-simulator-api');
    const allocations = { meta_ads: 200000, google_ads: 150000, tiktok_ads: 50000 };
    await simulate(allocations);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/budget-simulator/simulate');
    expect(opts.method).toBe('POST');

    const body = JSON.parse(opts.body as string);
    expect(body.allocations).toEqual(allocations);
    expect(body.lookback_days).toBeUndefined();
  });

  it('includes lookback_days in body when provided', async () => {
    const mockResponse = makeMockSimResult();
    const fetchMock = makeFetchMock(mockResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { simulate } = await import('@/lib/budget-simulator-api');
    await simulate({ meta_ads: 200000 }, 60);

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.lookback_days).toBe(60);
  });

  it('parses channels, projected_totals, baseline_totals, deltas, and assumptions', async () => {
    const mockResponse = makeMockSimResult();
    const fetchMock = makeFetchMock(mockResponse);
    vi.stubGlobal('fetch', fetchMock);

    const { simulate } = await import('@/lib/budget-simulator-api');
    const result = await simulate({ meta_ads: 200000 });

    expect(result.channels).toHaveLength(1);
    expect(result.channels[0].spend_delta_pct).toBe(11.11);
    expect(result.projected_totals.spend).toBe(400000);
    expect(result.baseline_totals.spend).toBe(452149);
    expect(result.deltas.roas_pct).toBe(-1.2);
    expect(result.deltas.conversions_pct).toBe(3.1);
    expect(result.assumptions).toHaveLength(2);
    expect(result.assumptions[0]).toContain('Son 30');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve('Geçersiz bütçe'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { simulate } = await import('@/lib/budget-simulator-api');
    await expect(simulate({ meta_ads: 200000 })).rejects.toThrow('Geçersiz bütçe');
  });
});
