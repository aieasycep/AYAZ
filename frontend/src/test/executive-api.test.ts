import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  ExecutiveOverview,
  ChannelRoi,
  ExecGoal,
  ExecInsight,
  Kpis,
  KpiDeltas,
} from '@/lib/executive-api';

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('ExecutiveOverview type', () => {
  it('accepts a full overview payload', () => {
    const overview: ExecutiveOverview = {
      period: {
        date_from: '2026-05-29',
        date_to: '2026-06-28',
        prev_date_from: '2026-04-29',
        prev_date_to: '2026-05-28',
      },
      kpis: {
        spend: 150000,
        revenue: 510000,
        conversions: 4200,
        clicks: 98000,
        roas: 3.4,
        deltas: {
          spend_pct: 5.2,
          revenue_pct: 12.8,
          conversions_pct: -3.1,
          roas_pct: 7.2,
        },
      },
      channels: [
        {
          channel: 'meta_ads',
          label: 'Meta Ads',
          spend: 80000,
          revenue: 280000,
          roas: 3.5,
          share_pct: 53.3,
        },
      ],
      goals: [
        {
          name: 'Gelir Hedefi',
          metric: 'revenue',
          current_value: 510000,
          target_value: 600000,
          pct_to_target: 85,
          status: 'on_track',
        },
      ],
      insights: [
        {
          severity: 'warning',
          title: 'TikTok ROAS düşüyor',
          channel: 'tiktok_ads',
        },
      ],
      headline:
        'Bu ay toplam 510.000 TL gelir elde edildi; ROAS 3.4x ile geçen aya göre %7 arttı.',
    };

    expect(overview.kpis.spend).toBe(150000);
    expect(overview.channels).toHaveLength(1);
    expect(overview.goals[0].status).toBe('on_track');
    expect(overview.insights[0].severity).toBe('warning');
    expect(overview.headline).toContain('510.000');
  });
});

describe('KpiDeltas type', () => {
  it('allows null values for each delta field', () => {
    const deltas: KpiDeltas = {
      spend_pct: null,
      revenue_pct: null,
      conversions_pct: null,
      roas_pct: null,
    };
    expect(deltas.spend_pct).toBeNull();
    expect(deltas.roas_pct).toBeNull();
  });

  it('accepts numeric values', () => {
    const deltas: KpiDeltas = {
      spend_pct: 5.5,
      revenue_pct: -2.3,
      conversions_pct: 0,
      roas_pct: 11.1,
    };
    expect(deltas.spend_pct).toBe(5.5);
    expect(deltas.revenue_pct).toBe(-2.3);
  });
});

describe('ChannelRoi type', () => {
  it('carries all required fields', () => {
    const ch: ChannelRoi = {
      channel: 'google_ads',
      label: 'Google Ads',
      spend: 50000,
      revenue: 175000,
      roas: 3.5,
      share_pct: 33.3,
    };
    expect(ch.channel).toBe('google_ads');
    expect(ch.roas).toBe(3.5);
    expect(ch.share_pct).toBe(33.3);
  });
});

describe('ExecGoal type', () => {
  it('carries name, metric, values, pct_to_target, status', () => {
    const goal: ExecGoal = {
      name: 'Dönüşüm Hedefi',
      metric: 'conversions',
      current_value: 3200,
      target_value: 5000,
      pct_to_target: 64,
      status: 'at_risk',
    };
    expect(goal.pct_to_target).toBe(64);
    expect(goal.status).toBe('at_risk');
  });
});

describe('ExecInsight type', () => {
  it('accepts channel as null', () => {
    const ins: ExecInsight = {
      severity: 'info',
      title: 'Genel performans iyileşti',
      channel: null,
    };
    expect(ins.channel).toBeNull();
    expect(ins.severity).toBe('info');
  });

  it('accepts channel as string', () => {
    const ins: ExecInsight = {
      severity: 'critical',
      title: 'Meta ROAS kritik düzeyde düştü',
      channel: 'meta_ads',
    };
    expect(ins.channel).toBe('meta_ads');
  });
});

describe('Kpis type', () => {
  it('includes clicks and roas alongside spend/revenue/conversions', () => {
    const kpis: Kpis = {
      spend: 100000,
      revenue: 340000,
      conversions: 2800,
      clicks: 55000,
      roas: 3.4,
      deltas: {
        spend_pct: 2.1,
        revenue_pct: 8.5,
        conversions_pct: null,
        roas_pct: 6.1,
      },
    };
    expect(kpis.clicks).toBe(55000);
    expect(kpis.roas).toBe(3.4);
    expect(kpis.deltas.conversions_pct).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// getExecutiveOverview — fetch mock
// ---------------------------------------------------------------------------

const MOCK_OVERVIEW: ExecutiveOverview = {
  period: {
    date_from: '2026-05-29',
    date_to: '2026-06-28',
    prev_date_from: '2026-04-29',
    prev_date_to: '2026-05-28',
  },
  kpis: {
    spend: 150000,
    revenue: 510000,
    conversions: 4200,
    clicks: 98000,
    roas: 3.4,
    deltas: {
      spend_pct: 5.2,
      revenue_pct: 12.8,
      conversions_pct: -3.1,
      roas_pct: 7.2,
    },
  },
  channels: [
    {
      channel: 'meta_ads',
      label: 'Meta Ads',
      spend: 80000,
      revenue: 280000,
      roas: 3.5,
      share_pct: 53.3,
    },
    {
      channel: 'google_ads',
      label: 'Google Ads',
      spend: 70000,
      revenue: 230000,
      roas: 3.29,
      share_pct: 46.7,
    },
  ],
  goals: [
    {
      name: 'Gelir Hedefi',
      metric: 'revenue',
      current_value: 510000,
      target_value: 600000,
      pct_to_target: 85,
      status: 'on_track',
    },
  ],
  insights: [
    {
      severity: 'warning',
      title: 'TikTok ROAS düşüyor',
      channel: 'tiktok_ads',
    },
  ],
  headline:
    'Bu ay toplam 510.000 TL gelir elde edildi; ROAS 3.4x ile geçen aya göre %7 arttı.',
};

describe('getExecutiveOverview', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: (_key: string) => 'exec-test-token',
      removeItem: vi.fn(),
      setItem: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls GET /api/v1/executive/overview with no query string when no options given', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(MOCK_OVERVIEW),
      text: () => Promise.resolve(JSON.stringify(MOCK_OVERVIEW)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getExecutiveOverview } = await import('@/lib/executive-api');
    const result = await getExecutiveOverview();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/executive/overview');
    expect(url).not.toContain('?');
    expect(result.kpis.spend).toBe(150000);
    expect(result.kpis.revenue).toBe(510000);
  });

  it('appends date_from and date_to when both are provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(MOCK_OVERVIEW),
      text: () => Promise.resolve(JSON.stringify(MOCK_OVERVIEW)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getExecutiveOverview } = await import('@/lib/executive-api');
    await getExecutiveOverview({ date_from: '2026-06-01', date_to: '2026-06-28' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).toContain('date_to=2026-06-28');
  });

  it('appends only date_from when date_to is omitted', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(MOCK_OVERVIEW),
      text: () => Promise.resolve(JSON.stringify(MOCK_OVERVIEW)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getExecutiveOverview } = await import('@/lib/executive-api');
    await getExecutiveOverview({ date_from: '2026-06-01' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).not.toContain('date_to=');
  });

  it('sends Bearer token from localStorage in the Authorization header', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(MOCK_OVERVIEW),
      text: () => Promise.resolve(JSON.stringify(MOCK_OVERVIEW)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getExecutiveOverview } = await import('@/lib/executive-api');
    await getExecutiveOverview();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer exec-test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('returns correctly parsed ExecutiveOverview including channels, goals and insights', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(MOCK_OVERVIEW),
      text: () => Promise.resolve(JSON.stringify(MOCK_OVERVIEW)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getExecutiveOverview } = await import('@/lib/executive-api');
    const result = await getExecutiveOverview();

    expect(result.channels).toHaveLength(2);
    expect(result.channels[0].channel).toBe('meta_ads');
    expect(result.goals).toHaveLength(1);
    expect(result.goals[0].pct_to_target).toBe(85);
    expect(result.insights[0].severity).toBe('warning');
    expect(result.headline).toContain('510.000');
  });

  it('throws with the server error message when response is not ok', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getExecutiveOverview } = await import('@/lib/executive-api');
    await expect(getExecutiveOverview()).rejects.toThrow('Sunucu hatası');
  });

  it('throws "Oturum süresi doldu" on 401', async () => {
    // Stub window so the redirect branch is skipped cleanly
    vi.stubGlobal('window', {
      location: { href: '' },
      localStorage: {
        getItem: () => 'exec-test-token',
        removeItem: vi.fn(),
        setItem: vi.fn(),
      },
    });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getExecutiveOverview } = await import('@/lib/executive-api');
    await expect(getExecutiveOverview()).rejects.toThrow('Oturum süresi doldu');
  });
});
