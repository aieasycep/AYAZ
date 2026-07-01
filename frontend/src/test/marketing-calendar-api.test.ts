import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  Opportunity,
  OpportunityReadiness,
  OpportunityAction,
  OpportunityCalendar,
} from '@/lib/marketing-calendar-api';
import { CATEGORY_LABELS, WEIGHT_LABELS } from '@/lib/marketing-calendar-api';

// ---------------------------------------------------------------------------
// Label map constants
// ---------------------------------------------------------------------------

describe('CATEGORY_LABELS', () => {
  it('maps all four categories to correct Turkish labels', () => {
    expect(CATEGORY_LABELS.ticari).toBe('Ticari');
    expect(CATEGORY_LABELS.resmi).toBe('Resmi');
    expect(CATEGORY_LABELS.sezonsal).toBe('Sezonsal');
    expect(CATEGORY_LABELS.dini).toBe('Dini');
  });

  it('covers exactly the four OppCategory values', () => {
    const keys = Object.keys(CATEGORY_LABELS);
    expect(keys).toHaveLength(4);
    expect(keys).toContain('ticari');
    expect(keys).toContain('resmi');
    expect(keys).toContain('sezonsal');
    expect(keys).toContain('dini');
  });
});

describe('WEIGHT_LABELS', () => {
  it('maps all three weights to correct Turkish labels', () => {
    expect(WEIGHT_LABELS.yuksek).toBe('Yüksek');
    expect(WEIGHT_LABELS.orta).toBe('Orta');
    expect(WEIGHT_LABELS.dusuk).toBe('Düşük');
  });

  it('covers exactly the three CommerceWeight values', () => {
    const keys = Object.keys(WEIGHT_LABELS);
    expect(keys).toHaveLength(3);
    expect(keys).toContain('yuksek');
    expect(keys).toContain('orta');
    expect(keys).toContain('dusuk');
  });
});

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('OpportunityReadiness type', () => {
  it('accepts a full readiness payload', () => {
    const readiness: OpportunityReadiness = {
      content_scheduled: 2,
      budget_planned: true,
    };
    expect(readiness.content_scheduled).toBe(2);
    expect(readiness.budget_planned).toBe(true);
  });
});

describe('OpportunityAction type', () => {
  it('accepts a full action payload', () => {
    const action: OpportunityAction = {
      label: 'İçerik planla',
      href: '/content',
    };
    expect(action.label).toBe('İçerik planla');
    expect(action.href).toBe('/content');
  });
});

describe('Opportunity type', () => {
  it('accepts a full opportunity payload', () => {
    const opp: Opportunity = {
      date: '2026-08-30',
      name: '30 Ağustos Zafer Bayramı',
      category: 'resmi',
      commerce_weight: 'dusuk',
      is_approximate: false,
      days_until: 62,
      lead_time_days: 14,
      status: 'upcoming',
      marketing_tip: 'Millî duygu ile marka değerini buluşturun.',
      readiness: { content_scheduled: 0, budget_planned: false },
      suggested_actions: [
        { label: 'İçerik planla', href: '/content' },
        { label: 'Reklam metni üret', href: '/ad-studio' },
      ],
    };
    expect(opp.name).toBe('30 Ağustos Zafer Bayramı');
    expect(opp.category).toBe('resmi');
    expect(opp.commerce_weight).toBe('dusuk');
    expect(opp.suggested_actions).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// getOpportunities — fetch mock
// ---------------------------------------------------------------------------

function makeMockCalendar(): OpportunityCalendar {
  return {
    as_of: '2026-06-29',
    horizon_months: 6,
    summary: {
      total: 8,
      urgent: 1,
      this_month: 0,
      high_weight: 5,
    },
    opportunities: [
      {
        date: '2026-08-30',
        name: '30 Ağustos Zafer Bayramı',
        category: 'resmi',
        commerce_weight: 'dusuk',
        is_approximate: false,
        days_until: 62,
        lead_time_days: 14,
        status: 'upcoming',
        marketing_tip: 'Millî duygu ile marka değerini buluşturun.',
        readiness: { content_scheduled: 0, budget_planned: false },
        suggested_actions: [
          { label: 'İçerik planla', href: '/content' },
          { label: 'Reklam metni üret', href: '/ad-studio' },
        ],
      },
    ],
  };
}

describe('getOpportunities', () => {
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

  it('parses summary and opportunities including readiness and suggested_actions', async () => {
    const mockResponse = makeMockCalendar();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOpportunities } = await import('@/lib/marketing-calendar-api');
    const result = await getOpportunities();

    expect(result.summary.total).toBe(8);
    expect(result.summary.urgent).toBe(1);
    expect(result.summary.this_month).toBe(0);
    expect(result.summary.high_weight).toBe(5);

    expect(result.opportunities).toHaveLength(1);
    const opp = result.opportunities[0];
    expect(opp.name).toBe('30 Ağustos Zafer Bayramı');
    expect(opp.readiness.content_scheduled).toBe(0);
    expect(opp.readiness.budget_planned).toBe(false);
    expect(opp.suggested_actions).toHaveLength(2);
    expect(opp.suggested_actions[0].label).toBe('İçerik planla');
    expect(opp.suggested_actions[1].href).toBe('/ad-studio');
  });

  it('builds ?horizon_months query param when horizonMonths is passed', async () => {
    const mockResponse = makeMockCalendar();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOpportunities } = await import('@/lib/marketing-calendar-api');
    await getOpportunities(6);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/marketing-calendar/opportunities');
    expect(url).toContain('horizon_months=6');
  });

  it('omits query string when horizonMonths is not passed', async () => {
    const mockResponse = makeMockCalendar();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOpportunities } = await import('@/lib/marketing-calendar-api');
    await getOpportunities();

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/marketing-calendar/opportunities');
    expect(url).not.toContain('?');
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse = makeMockCalendar();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOpportunities } = await import('@/lib/marketing-calendar-api');
    await getOpportunities();

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

    const { getOpportunities } = await import('@/lib/marketing-calendar-api');
    await expect(getOpportunities()).rejects.toThrow('Sunucu hatası');
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

    const { getOpportunities } = await import('@/lib/marketing-calendar-api');
    await expect(getOpportunities()).rejects.toThrow('Oturum süresi doldu');
  });
});
