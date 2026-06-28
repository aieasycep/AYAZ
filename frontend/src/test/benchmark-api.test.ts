import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { Benchmark, BenchmarkMetric, BenchmarkChannel, BenchPosition } from '@/lib/benchmark-api';
import { POSITION_LABELS } from '@/lib/benchmark-api';

// ---------------------------------------------------------------------------
// POSITION_LABELS constant
// ---------------------------------------------------------------------------

describe('POSITION_LABELS', () => {
  it('maps all three positions to correct Turkish labels', () => {
    expect(POSITION_LABELS.strong).toBe('Güçlü');
    expect(POSITION_LABELS.average).toBe('Ortalama');
    expect(POSITION_LABELS.weak).toBe('Zayıf');
  });

  it('covers exactly the three BenchPosition values', () => {
    const keys = Object.keys(POSITION_LABELS) as BenchPosition[];
    expect(keys).toHaveLength(3);
    expect(keys).toContain('strong');
    expect(keys).toContain('average');
    expect(keys).toContain('weak');
  });
});

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('BenchmarkMetric type', () => {
  it('accepts a full metric payload', () => {
    const metric: BenchmarkMetric = {
      key: 'roas',
      label: 'ROAS',
      unit: 'x',
      your_value: 4.2,
      ref_low: 2.0,
      ref_mid: 3.5,
      ref_high: 6.0,
      higher_is_better: true,
      position: 'strong',
      verdict: 'Sektör ortalamasının üzerinde ROAS değeri.',
    };
    expect(metric.key).toBe('roas');
    expect(metric.position).toBe('strong');
    expect(metric.unit).toBe('x');
  });
});

describe('BenchmarkChannel type', () => {
  it('accepts a full channel payload', () => {
    const ch: BenchmarkChannel = {
      channel: 'meta',
      label: 'Meta Ads',
      roas: 4.5,
      ctr: 1.2,
      roas_position: 'strong',
      ctr_position: 'average',
    };
    expect(ch.channel).toBe('meta');
    expect(ch.roas_position).toBe('strong');
    expect(ch.ctr_position).toBe('average');
  });
});

// ---------------------------------------------------------------------------
// getBenchmark — fetch mock
// ---------------------------------------------------------------------------

function makeMockBenchmark(): Benchmark {
  return {
    period: { date_from: '2026-05-29', date_to: '2026-06-28' },
    vertical: 'E-ticaret',
    metrics: [
      {
        key: 'roas',
        label: 'ROAS',
        unit: 'x',
        your_value: 4.2,
        ref_low: 2.0,
        ref_mid: 3.5,
        ref_high: 6.0,
        higher_is_better: true,
        position: 'strong',
        verdict: 'Sektör ortalamasının üzerinde.',
      },
    ],
    channels: [
      {
        channel: 'meta',
        label: 'Meta Ads',
        roas: 4.5,
        ctr: 1.2,
        roas_position: 'strong',
        ctr_position: 'average',
      },
    ],
    headline: 'Metriklerinizin çoğu sektör ortalamasının üzerinde.',
    summary_counts: { strong: 3, average: 2, weak: 1 },
  };
}

describe('getBenchmark', () => {
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

  it('GETs /api/v1/benchmark/overview with no query string when no options given', async () => {
    const mockResponse = makeMockBenchmark();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBenchmark } = await import('@/lib/benchmark-api');
    const result = await getBenchmark();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/benchmark/overview');
    expect(url).not.toContain('?');
    expect(result.vertical).toBe('E-ticaret');
    expect(result.metrics).toHaveLength(1);
  });

  it('appends date_from and date_to as query parameters when given', async () => {
    const mockResponse = makeMockBenchmark();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBenchmark } = await import('@/lib/benchmark-api');
    await getBenchmark({ date_from: '2026-06-01', date_to: '2026-06-28' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).toContain('date_to=2026-06-28');
  });

  it('appends only date_from when date_to is omitted', async () => {
    const mockResponse = makeMockBenchmark();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBenchmark } = await import('@/lib/benchmark-api');
    await getBenchmark({ date_from: '2026-06-01' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).not.toContain('date_to=');
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse = makeMockBenchmark();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBenchmark } = await import('@/lib/benchmark-api');
    await getBenchmark();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('returns the parsed Benchmark object with summary_counts', async () => {
    const mockResponse = makeMockBenchmark();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBenchmark } = await import('@/lib/benchmark-api');
    const result = await getBenchmark();

    expect(result.headline).toBe('Metriklerinizin çoğu sektör ortalamasının üzerinde.');
    expect(result.summary_counts.strong).toBe(3);
    expect(result.summary_counts.average).toBe(2);
    expect(result.summary_counts.weak).toBe(1);
    expect(result.channels[0].label).toBe('Meta Ads');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBenchmark } = await import('@/lib/benchmark-api');
    await expect(getBenchmark()).rejects.toThrow('Sunucu hatası');
  });

  it('throws with "Oturum süresi doldu" on 401', async () => {
    // Prevent window.location.href redirect in test environment
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

    const { getBenchmark } = await import('@/lib/benchmark-api');
    await expect(getBenchmark()).rejects.toThrow('Oturum süresi doldu');
  });
});
