import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  TrackingStats,
  EventStat,
  DailyPoint,
  GetSourceStatsOptions,
  EventConfigResponse,
  TrackingSource,
  TrackingDestination,
  ConsentSignal,
} from '@/lib/tracking-api';
import {
  ALL_CONSENT_SIGNALS,
  CONSENT_SIGNAL_LABELS,
  PLATFORM_DEFAULT_CONSENT,
} from '@/lib/tracking-api';

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
  it('carries event_name, count, errors, and enabled', () => {
    const ev: EventStat = { event_name: 'AddToCart', count: 1266, errors: 3, enabled: true };
    expect(ev.event_name).toBe('AddToCart');
    expect(ev.count).toBe(1266);
    expect(ev.errors).toBe(3);
    expect(ev.enabled).toBe(true);
  });

  it('enabled can be false for a disabled event', () => {
    const ev: EventStat = { event_name: 'PageView', count: 500, errors: 0, enabled: false };
    expect(ev.enabled).toBe(false);
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

// ---------------------------------------------------------------------------
// toggleEventConfig — fetch mock
// ---------------------------------------------------------------------------

describe('toggleEventConfig', () => {
  beforeEach(() => {
    // Stub localStorage so getToken() returns a predictable token.
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

  it('POSTs to /api/v1/tracking/sources/{id}/event-config with enabled=true', async () => {
    const mockResponse: EventConfigResponse = { disabled_events: [] };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { toggleEventConfig } = await import('@/lib/tracking-api');
    const result = await toggleEventConfig('src-001', 'PageView', true);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/tracking/sources/src-001/event-config');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body as string)).toEqual({ event_name: 'PageView', enabled: true });
    expect(result.disabled_events).toEqual([]);
  });

  it('POSTs with enabled=false and returns the disabled_events list from the server', async () => {
    const mockResponse: EventConfigResponse = { disabled_events: ['PageView', 'AddToCart'] };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { toggleEventConfig } = await import('@/lib/tracking-api');
    const result = await toggleEventConfig('src-001', 'PageView', false);

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(opts.body as string)).toEqual({ event_name: 'PageView', enabled: false });
    expect(result.disabled_events).toContain('PageView');
    expect(result.disabled_events).toHaveLength(2);
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse: EventConfigResponse = { disabled_events: [] };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { toggleEventConfig } = await import('@/lib/tracking-api');
    await toggleEventConfig('src-999', 'Purchase', true);

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('throws when the server returns a non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve('Geçersiz olay adı'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { toggleEventConfig } = await import('@/lib/tracking-api');
    await expect(
      toggleEventConfig('src-bad', 'UnknownEvent', false),
    ).rejects.toThrow('Geçersiz olay adı');
  });

  it('uses the source_id from the argument in the URL, not a hardcoded value', async () => {
    const mockResponse: EventConfigResponse = { disabled_events: [] };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { toggleEventConfig } = await import('@/lib/tracking-api');
    await toggleEventConfig('src-unique-42', 'Checkout', true);

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('src-unique-42');
    expect(url).not.toContain('src-001');
  });
});

// ---------------------------------------------------------------------------
// Consent signal constants
// ---------------------------------------------------------------------------

describe('CONSENT_SIGNAL_LABELS', () => {
  it('maps all four Consent Mode v2 signals to Turkish labels', () => {
    expect(CONSENT_SIGNAL_LABELS.ad_storage).toBe('Reklam Depolama');
    expect(CONSENT_SIGNAL_LABELS.ad_user_data).toBe('Reklam Kullanıcı Verisi');
    expect(CONSENT_SIGNAL_LABELS.ad_personalization).toBe('Reklam Kişiselleştirme');
    expect(CONSENT_SIGNAL_LABELS.analytics_storage).toBe('Analitik Depolama');
  });

  it('covers exactly the four standard signals', () => {
    const keys = Object.keys(CONSENT_SIGNAL_LABELS);
    expect(keys).toHaveLength(4);
    expect(keys).toContain('ad_storage');
    expect(keys).toContain('ad_user_data');
    expect(keys).toContain('ad_personalization');
    expect(keys).toContain('analytics_storage');
  });
});

describe('ALL_CONSENT_SIGNALS', () => {
  it('contains all four signals', () => {
    expect(ALL_CONSENT_SIGNALS).toHaveLength(4);
    expect(ALL_CONSENT_SIGNALS).toContain('ad_storage');
    expect(ALL_CONSENT_SIGNALS).toContain('ad_user_data');
    expect(ALL_CONSENT_SIGNALS).toContain('ad_personalization');
    expect(ALL_CONSENT_SIGNALS).toContain('analytics_storage');
  });
});

describe('PLATFORM_DEFAULT_CONSENT', () => {
  it('meta_capi defaults to [ad_user_data]', () => {
    expect(PLATFORM_DEFAULT_CONSENT.meta_capi).toEqual(['ad_user_data']);
  });

  it('tiktok_events defaults to [ad_user_data]', () => {
    expect(PLATFORM_DEFAULT_CONSENT.tiktok_events).toEqual(['ad_user_data']);
  });

  it('ga4_mp defaults to [analytics_storage]', () => {
    expect(PLATFORM_DEFAULT_CONSENT.ga4_mp).toEqual(['analytics_storage']);
  });
});

// ---------------------------------------------------------------------------
// TrackingSource — consent_cookie_var field
// ---------------------------------------------------------------------------

describe('TrackingSource type — consent_cookie_var', () => {
  it('accepts consent_cookie_var as a string', () => {
    const src: TrackingSource = {
      id: 'src-1',
      name: 'Test',
      domain: 'example.com',
      public_token: 'tok-1',
      created_at: '2026-01-01T00:00:00Z',
      consent_cookie_var: 'window.cookieConsent',
    };
    expect(src.consent_cookie_var).toBe('window.cookieConsent');
  });

  it('accepts consent_cookie_var as null', () => {
    const src: TrackingSource = {
      id: 'src-2',
      name: 'Test2',
      domain: 'example.com',
      public_token: 'tok-2',
      created_at: '2026-01-01T00:00:00Z',
      consent_cookie_var: null,
    };
    expect(src.consent_cookie_var).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// TrackingDestination — required_consent field
// ---------------------------------------------------------------------------

describe('TrackingDestination type — required_consent', () => {
  it('accepts required_consent as an array of signals', () => {
    const dest: TrackingDestination = {
      id: 'dest-1',
      tracking_source_id: 'src-1',
      platform: 'meta_capi',
      config: { pixel_id: '12345', access_token: 'EAA' },
      consent_required: true,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      required_consent: ['ad_user_data', 'ad_storage'],
    };
    expect(dest.required_consent).toEqual(['ad_user_data', 'ad_storage']);
  });

  it('accepts required_consent as null (platform default)', () => {
    const dest: TrackingDestination = {
      id: 'dest-2',
      tracking_source_id: 'src-1',
      platform: 'ga4_mp',
      config: { measurement_id: 'G-XXX', api_secret: 'secret' },
      consent_required: false,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      required_consent: null,
    };
    expect(dest.required_consent).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// patchTrackingSource — consent_cookie_var
// ---------------------------------------------------------------------------

describe('patchTrackingSource — consent_cookie_var', () => {
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

  it('sends consent_cookie_var as a string in the PATCH body', async () => {
    const mockSource: TrackingSource = {
      id: 'src-1',
      name: 'Test',
      domain: 'example.com',
      public_token: 'tok-1',
      created_at: '2026-01-01T00:00:00Z',
      consent_cookie_var: 'window.cookieConsent',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockSource),
      text: () => Promise.resolve(JSON.stringify(mockSource)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchTrackingSource } = await import('@/lib/tracking-api');
    const result = await patchTrackingSource('src-1', {
      consent_cookie_var: 'window.cookieConsent',
    });

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/tracking/sources/src-1');
    expect(opts.method).toBe('PATCH');
    const body = JSON.parse(opts.body as string);
    expect(body.consent_cookie_var).toBe('window.cookieConsent');
    expect(result.consent_cookie_var).toBe('window.cookieConsent');
  });

  it('sends consent_cookie_var as null to clear the variable', async () => {
    const mockSource: TrackingSource = {
      id: 'src-2',
      name: 'Test2',
      domain: 'example.com',
      public_token: 'tok-2',
      created_at: '2026-01-01T00:00:00Z',
      consent_cookie_var: null,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockSource),
      text: () => Promise.resolve(JSON.stringify(mockSource)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchTrackingSource } = await import('@/lib/tracking-api');
    await patchTrackingSource('src-2', { consent_cookie_var: null });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.consent_cookie_var).toBeNull();
  });

  it('does not include consent_cookie_var when not provided', async () => {
    const mockSource: TrackingSource = {
      id: 'src-3',
      name: 'Test3',
      domain: 'example.com',
      public_token: 'tok-3',
      created_at: '2026-01-01T00:00:00Z',
      consent_cookie_var: null,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockSource),
      text: () => Promise.resolve(JSON.stringify(mockSource)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchTrackingSource } = await import('@/lib/tracking-api');
    await patchTrackingSource('src-3', { name: 'Updated' });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect('consent_cookie_var' in body).toBe(false);
    expect(body.name).toBe('Updated');
  });
});

// ---------------------------------------------------------------------------
// patchDestination — required_consent
// ---------------------------------------------------------------------------

describe('patchDestination — required_consent', () => {
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

  function makeMockDest(overrides: Partial<TrackingDestination> = {}): TrackingDestination {
    return {
      id: 'dest-1',
      tracking_source_id: 'src-1',
      platform: 'meta_capi',
      config: { pixel_id: '12345', access_token: 'EAA' },
      consent_required: true,
      is_active: true,
      created_at: '2026-01-01T00:00:00Z',
      required_consent: null,
      ...overrides,
    };
  }

  it('sends required_consent array in the PATCH body', async () => {
    const signals: ConsentSignal[] = ['ad_user_data', 'ad_personalization'];
    const mockDest = makeMockDest({ required_consent: signals });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockDest),
      text: () => Promise.resolve(JSON.stringify(mockDest)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchDestination } = await import('@/lib/tracking-api');
    const result = await patchDestination('dest-1', { required_consent: signals });

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/tracking/destinations/dest-1');
    expect(opts.method).toBe('PATCH');
    const body = JSON.parse(opts.body as string);
    expect(body.required_consent).toEqual(['ad_user_data', 'ad_personalization']);
    expect(result.required_consent).toEqual(signals);
  });

  it('sends required_consent as null to restore platform default', async () => {
    const mockDest = makeMockDest({ required_consent: null });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockDest),
      text: () => Promise.resolve(JSON.stringify(mockDest)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchDestination } = await import('@/lib/tracking-api');
    await patchDestination('dest-1', { required_consent: null });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.required_consent).toBeNull();
  });

  it('sends required_consent as empty array when user deselects all', async () => {
    const mockDest = makeMockDest({ required_consent: [] });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockDest),
      text: () => Promise.resolve(JSON.stringify(mockDest)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchDestination } = await import('@/lib/tracking-api');
    await patchDestination('dest-1', { required_consent: [] });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.required_consent).toEqual([]);
  });

  it('sends all four signals when full custom consent is set', async () => {
    const allSignals: ConsentSignal[] = [
      'ad_storage',
      'ad_user_data',
      'ad_personalization',
      'analytics_storage',
    ];
    const mockDest = makeMockDest({ required_consent: allSignals });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockDest),
      text: () => Promise.resolve(JSON.stringify(mockDest)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchDestination } = await import('@/lib/tracking-api');
    await patchDestination('dest-1', { required_consent: allSignals });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.required_consent).toHaveLength(4);
    expect(body.required_consent).toContain('analytics_storage');
  });

  it('can patch required_consent independently of other fields', async () => {
    const signals: ConsentSignal[] = ['analytics_storage'];
    const mockDest = makeMockDest({ platform: 'ga4_mp', required_consent: signals });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockDest),
      text: () => Promise.resolve(JSON.stringify(mockDest)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchDestination } = await import('@/lib/tracking-api');
    await patchDestination('dest-ga4', { required_consent: signals });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    // Only required_consent in body — no other fields
    expect(Object.keys(body)).toEqual(['required_consent']);
  });
});
