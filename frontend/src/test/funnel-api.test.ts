import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { FunnelOverview, FunnelStage, FunnelBiggestDropoff } from '@/lib/funnel-api';

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

function makeMockFunnel(): FunnelOverview {
  return {
    period: { date_from: '2026-05-29', date_to: '2026-06-28' },
    total_events: 100,
    stages: [
      {
        key: 'PageView',
        label: 'Sayfa Görüntüleme',
        count: 40,
        conversion_from_prev_pct: null,
        dropoff_count: 0,
        dropoff_pct: null,
        share_of_entry_pct: 100.0,
      },
      {
        key: 'ViewContent',
        label: 'Ürün Görüntüleme',
        count: 26,
        conversion_from_prev_pct: 65.0,
        dropoff_count: 14,
        dropoff_pct: 35.0,
        share_of_entry_pct: 65.0,
      },
      {
        key: 'AddToCart',
        label: 'Sepete Ekleme',
        count: 18,
        conversion_from_prev_pct: 69.2,
        dropoff_count: 8,
        dropoff_pct: 30.8,
        share_of_entry_pct: 45.0,
      },
      {
        key: 'InitiateCheckout',
        label: 'Ödeme Başlatma',
        count: 10,
        conversion_from_prev_pct: 55.6,
        dropoff_count: 8,
        dropoff_pct: 44.4,
        share_of_entry_pct: 25.0,
      },
      {
        key: 'Purchase',
        label: 'Satın Alma',
        count: 6,
        conversion_from_prev_pct: 60.0,
        dropoff_count: 4,
        dropoff_pct: 40.0,
        share_of_entry_pct: 15.0,
      },
    ],
    entry_count: 40,
    final_count: 6,
    overall_conversion_pct: 15.0,
    biggest_dropoff: {
      from_label: 'Sepete Ekleme',
      to_label: 'Ödeme Başlatma',
      dropoff_pct: 44.4,
    },
  };
}

function makeMockFunnelNullDropoff(): FunnelOverview {
  return {
    ...makeMockFunnel(),
    biggest_dropoff: null,
  };
}

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('FunnelStage type', () => {
  it('accepts a first stage with null conversion and dropoff', () => {
    const stage: FunnelStage = {
      key: 'PageView',
      label: 'Sayfa Görüntüleme',
      count: 40,
      conversion_from_prev_pct: null,
      dropoff_count: 0,
      dropoff_pct: null,
      share_of_entry_pct: 100.0,
    };
    expect(stage.conversion_from_prev_pct).toBeNull();
    expect(stage.dropoff_pct).toBeNull();
    expect(stage.share_of_entry_pct).toBe(100.0);
  });

  it('accepts a non-first stage with numeric conversion and dropoff', () => {
    const stage: FunnelStage = {
      key: 'Purchase',
      label: 'Satın Alma',
      count: 6,
      conversion_from_prev_pct: 60.0,
      dropoff_count: 4,
      dropoff_pct: 40.0,
      share_of_entry_pct: 15.0,
    };
    expect(stage.conversion_from_prev_pct).toBe(60.0);
    expect(stage.dropoff_pct).toBe(40.0);
  });
});

describe('FunnelBiggestDropoff type', () => {
  it('accepts a full biggest_dropoff payload', () => {
    const bd: FunnelBiggestDropoff = {
      from_label: 'Sepete Ekleme',
      to_label: 'Ödeme Başlatma',
      dropoff_pct: 44.4,
    };
    expect(bd.from_label).toBe('Sepete Ekleme');
    expect(bd.dropoff_pct).toBe(44.4);
  });
});

// ---------------------------------------------------------------------------
// getFunnel — fetch mock
// ---------------------------------------------------------------------------

describe('getFunnel', () => {
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

  it('GETs /api/v1/funnel/overview with no query string when no dates given', async () => {
    const mockResponse = makeMockFunnel();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    const result = await getFunnel();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/funnel/overview');
    expect(url).not.toContain('?');
    expect(result.stages).toHaveLength(5);
    expect(result.overall_conversion_pct).toBe(15.0);
  });

  it('appends date_from and date_to as query parameters when both given', async () => {
    const mockResponse = makeMockFunnel();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    await getFunnel('2026-06-01', '2026-06-28');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).toContain('date_to=2026-06-28');
  });

  it('appends only date_from when date_to is omitted', async () => {
    const mockResponse = makeMockFunnel();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    await getFunnel('2026-06-01');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).not.toContain('date_to=');
  });

  it('appends only date_to when date_from is omitted', async () => {
    const mockResponse = makeMockFunnel();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    await getFunnel(undefined, '2026-06-28');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_to=2026-06-28');
    expect(url).not.toContain('date_from=');
  });

  it('parses all 5 stages including the first stage with null conversion fields', async () => {
    const mockResponse = makeMockFunnel();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    const result = await getFunnel();

    const first = result.stages[0];
    expect(first.key).toBe('PageView');
    expect(first.conversion_from_prev_pct).toBeNull();
    expect(first.dropoff_pct).toBeNull();
    expect(first.share_of_entry_pct).toBe(100.0);

    const last = result.stages[4];
    expect(last.key).toBe('Purchase');
    expect(last.conversion_from_prev_pct).toBe(60.0);
    expect(last.dropoff_pct).toBe(40.0);
  });

  it('parses biggest_dropoff when present', async () => {
    const mockResponse = makeMockFunnel();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    const result = await getFunnel();

    expect(result.biggest_dropoff).not.toBeNull();
    expect(result.biggest_dropoff!.from_label).toBe('Sepete Ekleme');
    expect(result.biggest_dropoff!.to_label).toBe('Ödeme Başlatma');
    expect(result.biggest_dropoff!.dropoff_pct).toBe(44.4);
  });

  it('handles null biggest_dropoff gracefully', async () => {
    const mockResponse = makeMockFunnelNullDropoff();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    const result = await getFunnel();

    expect(result.biggest_dropoff).toBeNull();
    expect(result.entry_count).toBe(40);
    expect(result.final_count).toBe(6);
    expect(result.overall_conversion_pct).toBe(15.0);
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse = makeMockFunnel();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    await getFunnel();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getFunnel } = await import('@/lib/funnel-api');
    await expect(getFunnel()).rejects.toThrow('Sunucu hatası');
  });

  it('throws with "Oturum süresi doldu" on 401', async () => {
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

    const { getFunnel } = await import('@/lib/funnel-api');
    await expect(getFunnel()).rejects.toThrow('Oturum süresi doldu');
  });
});
