import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { TrackingStats, EventStat, DailyPoint, GetSourceStatsOptions } from '@/lib/tracking-api';

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('TrackingStats type', () => {
  it('accepts a full stats payload', () => {
    const stats: TrackingStats = {
      source_id: 'src-001',
      date_from: '2026-06-01',
      date_to: '2026-06-28',
      totals: {
        total_events: 4861,
        total_errors: 0,
        by_status: { forwarded: 4800, error: 0, no_consent: 61 },
        consent_blocked: 61,
      },
      by_event: [
        { event_name: 'PageView', count: 3000, errors: 0 },
        { event_name: 'AddToCart', count: 1266, errors: 0 },
        { event_name: 'Purchase', count: 595, errors: 0 },
      ],
      daily: [
        { date: '2026-06-01', count: 150, errors: 0 },
        { date: '2026-06-02', count: 210, errors: 0 },
      ],
    };
    expect(stats.totals.total_events).toBe(4861);
    expect(stats.by_event).toHaveLength(3);
    expect(stats.daily).toHaveLength(2);
    expect(stats.totals.consent_blocked).toBe(61);
  });

  it('accepts stats with errors > 0 and marks them in totals + by_event', () => {
    const stats: TrackingStats = {
      source_id: 'src-002',
      date_from: '2026-06-21',
      date_to: '2026-06-28',
      totals: {
        total_events: 500,
        total_errors: 12,
        by_status: { forwarded: 480, error: 12, received: 8 },
        consent_blocked: 0,
      },
      by_event: [
        { event_name: 'Purchase', count: 500, errors: 12 },
      ],
      daily: [],
    };
    expect(stats.totals.total_errors).toBe(12);
    expect(stats.by_event[0].errors).toBe(12);
  });
});

describe('EventStat type', () => {
  it('carries event_name, count, errors', () => {
    const ev: EventStat = { event_name: 'AddToCart', count: 1266, errors: 3 };
    expect(ev.event_name).toBe('AddToCart');
    expect(ev.count).toBe(1266);
    expect(ev.errors).toBe(3);
  });
});

describe('DailyPoint type', () => {
  it('carries date, count, errors', () => {
    const pt: DailyPoint = { date: '2026-06-15', count: 320, errors: 0 };
    expect(pt.date).toBe('2026-06-15');
    expect(pt.count).toBe(320);
    expect(pt.errors).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// getSourceStats — fetch mock
// ---------------------------------------------------------------------------

describe('getSourceStats', () => {
  beforeEach(() => {
    if (typeof globalThis.localStorage === 'undefined') {
      Object.defineProperty(globalThis, 'localStorage', {
        value: { getItem: () => 'test-token', removeItem: vi.fn(), setItem: vi.fn() },
        writable: true,
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls GET /api/v1/tracking/sources/{id}/stats with no query string when no options given', async () => {
    const mockResponse: TrackingStats = {
      source_id: 'src-abc',
      date_from: '2026-05-29',
      date_to: '2026-06-28',
      totals: { total_events: 100, total_errors: 0, by_status: {}, consent_blocked: 0 },
      by_event: [],
      daily: [],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceStats } = await import('@/lib/tracking-api');
    const result = await getSourceStats('src-abc');

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/tracking/sources/src-abc/stats');
    // No query string because no options passed
    expect(url).not.toContain('?');
    expect(result.source_id).toBe('src-abc');
    expect(result.totals.total_events).toBe(100);
  });

  it('appends date_from and date_to as query parameters when provided', async () => {
    const mockResponse: TrackingStats = {
      source_id: 'src-xyz',
      date_from: '2026-06-01',
      date_to: '2026-06-28',
      totals: { total_events: 4861, total_errors: 0, by_status: { forwarded: 4800 }, consent_blocked: 61 },
      by_event: [{ event_name: 'PageView', count: 3000, errors: 0 }],
      daily: [{ date: '2026-06-01', count: 150, errors: 0 }],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceStats } = await import('@/lib/tracking-api');
    const opts: GetSourceStatsOptions = { date_from: '2026-06-01', date_to: '2026-06-28' };
    const result = await getSourceStats('src-xyz', opts);

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).toContain('date_to=2026-06-28');
    expect(result.totals.total_events).toBe(4861);
    expect(result.by_event[0].event_name).toBe('PageView');
    expect(result.daily[0].date).toBe('2026-06-01');
    expect(result.totals.consent_blocked).toBe(61);
  });

  it('appends only date_from when date_to is omitted', async () => {
    const mockResponse: TrackingStats = {
      source_id: 'src-partial',
      date_from: '2026-06-01',
      date_to: '2026-06-28',
      totals: { total_events: 0, total_errors: 0, by_status: {}, consent_blocked: 0 },
      by_event: [],
      daily: [],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceStats } = await import('@/lib/tracking-api');
    await getSourceStats('src-partial', { date_from: '2026-06-01' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).not.toContain('date_to=');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatasi'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceStats } = await import('@/lib/tracking-api');
    await expect(getSourceStats('src-err')).rejects.toThrow('Sunucu hatasi');
  });

  it('returns by_event sorted verification: by_event order is preserved from backend', async () => {
    const mockResponse: TrackingStats = {
      source_id: 'src-sorted',
      date_from: '2026-06-01',
      date_to: '2026-06-28',
      totals: { total_events: 500, total_errors: 0, by_status: {}, consent_blocked: 0 },
      by_event: [
        { event_name: 'Purchase', count: 100, errors: 0 },
        { event_name: 'AddToCart', count: 300, errors: 0 },
        { event_name: 'PageView', count: 100, errors: 0 },
      ],
      daily: [],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceStats } = await import('@/lib/tracking-api');
    const result = await getSourceStats('src-sorted');
    // The API returns in backend order; by_event[1] is AddToCart (300 count)
    expect(result.by_event[1].event_name).toBe('AddToCart');
    expect(result.by_event[1].count).toBe(300);
  });
});

// ---------------------------------------------------------------------------
// getSourceEvents — extended options
// ---------------------------------------------------------------------------

describe('getSourceEvents — filter options', () => {
  beforeEach(() => {
    if (typeof globalThis.localStorage === 'undefined') {
      Object.defineProperty(globalThis, 'localStorage', {
        value: { getItem: () => 'test-token', removeItem: vi.fn(), setItem: vi.fn() },
        writable: true,
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('calls without query string when no options given (backward compat)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceEvents } = await import('@/lib/tracking-api');
    await getSourceEvents('src-001');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/tracking/sources/src-001/events');
    expect(url).not.toContain('?');
  });

  it('appends status filter when given', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceEvents } = await import('@/lib/tracking-api');
    await getSourceEvents('src-001', { status: 'error' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('status=error');
  });

  it('appends event_name and limit filters together', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceEvents } = await import('@/lib/tracking-api');
    await getSourceEvents('src-001', { event_name: 'Purchase', limit: 50 });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('event_name=Purchase');
    expect(url).toContain('limit=50');
  });

  it('normalises backend "failed" status to "error" in returned events', async () => {
    const rawEvent = {
      id: 'ev-1',
      event_name: 'Purchase',
      event_time: '2026-06-15T10:00:00Z',
      status: 'failed',
      forwarded_count: 0,
      error_detail: 'Timeout',
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([rawEvent]),
      text: () => Promise.resolve(JSON.stringify([rawEvent])),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceEvents } = await import('@/lib/tracking-api');
    const events = await getSourceEvents('src-001');

    expect(events[0].status).toBe('error');
    expect(events[0].error_detail).toBe('Timeout');
  });

  it('normalises backend "skipped_no_consent" status to "no_consent"', async () => {
    const rawEvent = {
      id: 'ev-2',
      event_name: 'Purchase',
      event_time: '2026-06-15T11:00:00Z',
      status: 'skipped_no_consent',
      forwarded_count: 0,
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([rawEvent]),
      text: () => Promise.resolve(JSON.stringify([rawEvent])),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getSourceEvents } = await import('@/lib/tracking-api');
    const events = await getSourceEvents('src-002');

    expect(events[0].status).toBe('no_consent');
  });
});
