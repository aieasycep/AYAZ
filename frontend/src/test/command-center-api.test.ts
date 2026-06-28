import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { CommandCenter, AttentionItem, CcKpis, CcModules } from '@/lib/command-center-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeFullPayload(): CommandCenter {
  return {
    headline: 'Bu ay geliriniz %18 arttı; bütçe temposu uyumlu seyrediyor.',
    kpis: {
      spend: 125000,
      revenue: 414000,
      roas: 3.31,
      conversions: 1842,
      deltas: {
        spend_pct: 5.2,
        revenue_pct: 18.4,
        roas_pct: 12.1,
        conversions_pct: null,
      },
    },
    attention: [
      {
        severity: 'critical',
        title: 'Meta kampanyası bütçesi tükendi',
        detail: 'Kampanya durdu, manuel müdahale gerekiyor.',
        module: 'Bütçe',
        link: '/planning',
      },
      {
        severity: 'warning',
        title: '3 içerik onay bekliyor',
        detail: '48 saatten uzun süredir beklemede.',
        module: 'İçerik',
        link: '/content',
      },
    ],
    modules: {
      budget: {
        has_plan: true,
        period_month: '2026-06',
        pace_pct: 72.5,
        pace_status: 'on_track',
      },
      inbox: { total: 88, open: 42, pending: 12, negative: 5 },
      content: { draft: 7, pending_approval: 3, scheduled: 14 },
      goals: { total: 8, at_risk: 2 },
      insights: { critical: 1, warning: 4 },
    },
  };
}

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('CommandCenter type', () => {
  it('accepts a full payload with all required fields', () => {
    const cc: CommandCenter = makeFullPayload();
    expect(cc.headline).toBeTruthy();
    expect(cc.kpis.spend).toBe(125000);
    expect(cc.attention).toHaveLength(2);
    expect(cc.modules.inbox.open).toBe(42);
  });

  it('accepts an empty attention array', () => {
    const cc: CommandCenter = { ...makeFullPayload(), attention: [] };
    expect(cc.attention).toHaveLength(0);
  });
});

describe('AttentionItem type', () => {
  it('carries all severity values', () => {
    const critical: AttentionItem = {
      severity: 'critical',
      title: 'Test',
      detail: 'Detail',
      module: 'Bütçe',
      link: '/planning',
    };
    const warning: AttentionItem = { ...critical, severity: 'warning' };
    const info: AttentionItem = { ...critical, severity: 'info' };
    expect(critical.severity).toBe('critical');
    expect(warning.severity).toBe('warning');
    expect(info.severity).toBe('info');
  });
});

describe('CcKpis type', () => {
  it('accepts null deltas', () => {
    const kpis: CcKpis = {
      spend: 0,
      revenue: 0,
      roas: 0,
      conversions: 0,
      deltas: {
        spend_pct: null,
        revenue_pct: null,
        roas_pct: null,
        conversions_pct: null,
      },
    };
    expect(kpis.deltas.spend_pct).toBeNull();
    expect(kpis.deltas.conversions_pct).toBeNull();
  });
});

describe('CcModules type', () => {
  it('accepts has_plan:false with null period and pace', () => {
    const mods: CcModules = {
      budget: { has_plan: false, period_month: null, pace_pct: null, pace_status: null },
      inbox: { total: 0, open: 0, pending: 0, negative: 0 },
      content: { draft: 0, pending_approval: 0, scheduled: 0 },
      goals: { total: 0, at_risk: 0 },
      insights: { critical: 0, warning: 0 },
    };
    expect(mods.budget.has_plan).toBe(false);
    expect(mods.budget.period_month).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// getCommandCenter — fetch mock
// ---------------------------------------------------------------------------

describe('getCommandCenter', () => {
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

  it('GETs /api/v1/command-center/overview', async () => {
    const mockPayload = makeFullPayload();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPayload),
      text: () => Promise.resolve(JSON.stringify(mockPayload)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCommandCenter } = await import('@/lib/command-center-api');
    await getCommandCenter();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/command-center/overview');
  });

  it('sends Authorization: Bearer from localStorage', async () => {
    const mockPayload = makeFullPayload();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPayload),
      text: () => Promise.resolve(JSON.stringify(mockPayload)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCommandCenter } = await import('@/lib/command-center-api');
    await getCommandCenter();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('returns the parsed CommandCenter object', async () => {
    const mockPayload = makeFullPayload();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPayload),
      text: () => Promise.resolve(JSON.stringify(mockPayload)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCommandCenter } = await import('@/lib/command-center-api');
    const result = await getCommandCenter();

    expect(result.headline).toBe(mockPayload.headline);
    expect(result.kpis.spend).toBe(125000);
    expect(result.kpis.roas).toBe(3.31);
    expect(result.attention).toHaveLength(2);
    expect(result.attention[0].severity).toBe('critical');
    expect(result.modules.budget.has_plan).toBe(true);
    expect(result.modules.goals.at_risk).toBe(2);
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası oluştu'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCommandCenter } = await import('@/lib/command-center-api');
    await expect(getCommandCenter()).rejects.toThrow('Sunucu hatası oluştu');
  });

  it('throws "Oturum süresi doldu" and does not return data on 401', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);
    // Stub window.location to prevent jsdom errors
    vi.stubGlobal('window', {
      location: { href: '' },
      localStorage: {
        getItem: () => 'test-token',
        removeItem: vi.fn(),
        setItem: vi.fn(),
      },
    });

    const { getCommandCenter } = await import('@/lib/command-center-api');
    await expect(getCommandCenter()).rejects.toThrow('Oturum süresi doldu');
  });

  it('handles an empty attention array gracefully', async () => {
    const mockPayload: CommandCenter = { ...makeFullPayload(), attention: [] };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPayload),
      text: () => Promise.resolve(JSON.stringify(mockPayload)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCommandCenter } = await import('@/lib/command-center-api');
    const result = await getCommandCenter();

    expect(result.attention).toHaveLength(0);
    expect(result.modules.insights.critical).toBe(1);
  });
});
