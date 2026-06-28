import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  AllocationResult,
  BudgetPlan,
  CampaignAllocation,
  PlatformAllocation,
} from '@/lib/budget-api';
import {
  OBJECTIVE_LABELS,
  STATUS_LABELS,
} from '@/lib/budget-api';

// ---------------------------------------------------------------------------
// Shared localStorage stub
// ---------------------------------------------------------------------------

function stubLocalStorage() {
  vi.stubGlobal('localStorage', {
    getItem: (_key: string) => 'test-token',
    removeItem: vi.fn(),
    setItem: vi.fn(),
  });
}

// ---------------------------------------------------------------------------
// Label map constants
// ---------------------------------------------------------------------------

describe('OBJECTIVE_LABELS', () => {
  it('maps all three objectives to Turkish labels', () => {
    expect(OBJECTIVE_LABELS.balanced).toBe('Dengeli');
    expect(OBJECTIVE_LABELS.maximize_roas).toBe("ROAS'ı Maksimize Et");
    expect(OBJECTIVE_LABELS.maximize_conversions).toBe('Dönüşümü Maksimize Et');
  });

  it('covers exactly three objectives', () => {
    expect(Object.keys(OBJECTIVE_LABELS)).toHaveLength(3);
  });
});

describe('STATUS_LABELS', () => {
  it('maps all three statuses to Turkish labels', () => {
    expect(STATUS_LABELS.draft).toBe('Taslak');
    expect(STATUS_LABELS.active).toBe('Aktif');
    expect(STATUS_LABELS.archived).toBe('Arşiv');
  });
});

// ---------------------------------------------------------------------------
// previewBudget
// ---------------------------------------------------------------------------

describe('previewBudget', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('POSTs to /api/v1/budget/preview with total_budget and objective', async () => {
    const mockResult: AllocationResult = {
      total_budget: 50000,
      currency: 'TRY',
      objective: 'balanced',
      lookback_days: 30,
      based_on: { date_from: '2026-05-29', date_to: '2026-06-28' },
      platforms: [],
      projection: { expected_conversions: 120, expected_revenue: 180000, expected_roas: 3.6 },
      notes: ['Geçmiş 30 günlük veriye göre hesaplandı.'],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResult),
      text: () => Promise.resolve(JSON.stringify(mockResult)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { previewBudget } = await import('@/lib/budget-api');
    const result = await previewBudget({ total_budget: 50000, objective: 'balanced' });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/budget/preview');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.total_budget).toBe(50000);
    expect(body.objective).toBe('balanced');
    expect(result.projection.expected_roas).toBe(3.6);
  });

  it('sends Bearer token in Authorization header', async () => {
    const mockResult: AllocationResult = {
      total_budget: 10000,
      currency: 'TRY',
      objective: 'maximize_roas',
      lookback_days: 60,
      based_on: { date_from: '2026-04-29', date_to: '2026-06-28' },
      platforms: [],
      projection: { expected_conversions: 40, expected_revenue: 60000, expected_roas: 6.0 },
      notes: [],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResult),
      text: () => Promise.resolve(JSON.stringify(mockResult)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { previewBudget } = await import('@/lib/budget-api');
    await previewBudget({ total_budget: 10000, objective: 'maximize_roas', lookback_days: 60 });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve('Geçersiz bütçe değeri'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { previewBudget } = await import('@/lib/budget-api');
    await expect(previewBudget({ total_budget: -1 })).rejects.toThrow('Geçersiz bütçe değeri');
  });
});

// ---------------------------------------------------------------------------
// createBudgetPlan
// ---------------------------------------------------------------------------

describe('createBudgetPlan', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('POSTs to /api/v1/budget/plans with the payload', async () => {
    const mockPlan: BudgetPlan = {
      id: 'plan-1',
      tenant_id: 'tenant-1',
      name: 'Temmuz Planı',
      period_month: '2026-07',
      total_budget: 75000,
      currency: 'TRY',
      objective: 'maximize_conversions',
      lookback_days: 30,
      allocations: null,
      status: 'draft',
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:00:00Z',
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve(mockPlan),
      text: () => Promise.resolve(JSON.stringify(mockPlan)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { createBudgetPlan } = await import('@/lib/budget-api');
    const result = await createBudgetPlan({
      name: 'Temmuz Planı',
      period_month: '2026-07',
      total_budget: 75000,
      objective: 'maximize_conversions',
    });

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/budget/plans');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.name).toBe('Temmuz Planı');
    expect(body.total_budget).toBe(75000);
    expect(result.id).toBe('plan-1');
    expect(result.status).toBe('draft');
  });
});

// ---------------------------------------------------------------------------
// getBudgetPlans
// ---------------------------------------------------------------------------

describe('getBudgetPlans', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/budget/plans and returns an array', async () => {
    const mockPlans: BudgetPlan[] = [
      {
        id: 'plan-a',
        tenant_id: 'tenant-1',
        name: 'Haziran Planı',
        period_month: '2026-06',
        total_budget: 40000,
        currency: 'TRY',
        objective: 'balanced',
        lookback_days: 30,
        allocations: null,
        status: 'active',
        created_at: '2026-06-01T00:00:00Z',
        updated_at: '2026-06-01T00:00:00Z',
      },
    ];

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPlans),
      text: () => Promise.resolve(JSON.stringify(mockPlans)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBudgetPlans } = await import('@/lib/budget-api');
    const result = await getBudgetPlans();

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/budget/plans');
    expect((opts.method ?? 'GET').toUpperCase()).toBe('GET');
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe('plan-a');
    expect(result[0].status).toBe('active');
  });

  it('returns an empty array when no plans exist', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getBudgetPlans } = await import('@/lib/budget-api');
    const result = await getBudgetPlans();
    expect(result).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// deleteBudgetPlan
// ---------------------------------------------------------------------------

describe('deleteBudgetPlan', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('sends DELETE to /api/v1/budget/plans/{id} and returns undefined for 204', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: () => Promise.resolve(undefined),
      text: () => Promise.resolve(''),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { deleteBudgetPlan } = await import('@/lib/budget-api');
    const result = await deleteBudgetPlan('plan-99');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/budget/plans/plan-99');
    expect(opts.method).toBe('DELETE');
    expect(result).toBeUndefined();
  });

  it('uses the id argument in the URL path', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: () => Promise.resolve(undefined),
      text: () => Promise.resolve(''),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { deleteBudgetPlan } = await import('@/lib/budget-api');
    await deleteBudgetPlan('unique-plan-id-42');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('unique-plan-id-42');
    expect(url).not.toContain('plan-99');
  });
});

// ---------------------------------------------------------------------------
// patchBudgetPlan
// ---------------------------------------------------------------------------

describe('patchBudgetPlan', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('sends PATCH to /api/v1/budget/plans/{id} with only the provided fields', async () => {
    const mockPlan: BudgetPlan = {
      id: 'plan-5',
      tenant_id: 'tenant-1',
      name: 'Güncellenmiş Plan',
      period_month: '2026-08',
      total_budget: 60000,
      currency: 'TRY',
      objective: 'maximize_roas',
      lookback_days: 90,
      allocations: null,
      status: 'active',
      created_at: '2026-06-01T00:00:00Z',
      updated_at: '2026-06-28T12:00:00Z',
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPlan),
      text: () => Promise.resolve(JSON.stringify(mockPlan)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { patchBudgetPlan } = await import('@/lib/budget-api');
    const result = await patchBudgetPlan('plan-5', { status: 'active' });

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/budget/plans/plan-5');
    expect(opts.method).toBe('PATCH');
    const body = JSON.parse(opts.body as string);
    expect(body.status).toBe('active');
    expect(result.status).toBe('active');
  });
});

// ---------------------------------------------------------------------------
// AllocationResult + PlatformAllocation + CampaignAllocation types
// ---------------------------------------------------------------------------

describe('AllocationResult type', () => {
  it('accepts a full allocation result with platforms and campaigns', () => {
    const campaign: CampaignAllocation = {
      campaign_id: 'c-1',
      name: 'Marka Kampanyası',
      recommended_budget: 15000,
      recommended_share: 0.3,
      roas: 4.5,
      expected_conversions: 50,
      expected_revenue: 67500,
    };

    const platform: PlatformAllocation = {
      channel: 'google_ads',
      label: 'Google Ads',
      historical_spend: 40000,
      historical_share: 0.5,
      roas: 4.2,
      cpa: 120,
      recommended_budget: 50000,
      recommended_share: 0.5,
      delta_pct: 25,
      expected_conversions: 100,
      expected_revenue: 210000,
      expected_roas: 4.2,
      campaigns: [campaign],
    };

    const result: AllocationResult = {
      total_budget: 100000,
      currency: 'TRY',
      objective: 'balanced',
      lookback_days: 30,
      based_on: { date_from: '2026-05-29', date_to: '2026-06-28' },
      platforms: [platform],
      projection: {
        expected_conversions: 200,
        expected_revenue: 420000,
        expected_roas: 4.2,
      },
      notes: ['Geçmiş verilere göre Google Ads en yüksek ROAS sağladı.'],
    };

    expect(result.total_budget).toBe(100000);
    expect(result.platforms).toHaveLength(1);
    expect(result.platforms[0].campaigns).toHaveLength(1);
    expect(result.platforms[0].campaigns[0].campaign_id).toBe('c-1');
    expect(result.notes).toHaveLength(1);
  });
});
