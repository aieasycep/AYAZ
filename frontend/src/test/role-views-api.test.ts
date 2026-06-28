import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  RoleSummary,
  RoleView,
  RoleMetric,
  RoleAttention,
  RolePriorityScreen,
  RoleQuickAction,
  RoleKey,
  AttentionSeverity,
} from '@/lib/role-views-api';

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('RoleSummary type', () => {
  it('accepts a full role summary payload', () => {
    const summary: RoleSummary = {
      key: 'performans',
      label: 'Performans Pazarlamacısı',
      description: 'Reklam harcamaları, ROAS ve kampanya optimizasyonu.',
      icon_key: 'trending',
    };
    expect(summary.key).toBe('performans');
    expect(summary.icon_key).toBe('trending');
  });
});

describe('RoleMetric type', () => {
  it('accepts a full metric payload', () => {
    const metric: RoleMetric = {
      label: 'Harcama',
      value: '₺452.149',
      hint: 'Son 30 gün',
    };
    expect(metric.label).toBe('Harcama');
    expect(metric.value).toBe('₺452.149');
    expect(metric.hint).toBe('Son 30 gün');
  });
});

describe('RoleAttention type', () => {
  it('accepts all severity values', () => {
    const severities: AttentionSeverity[] = ['high', 'medium', 'low'];
    severities.forEach((severity) => {
      const item: RoleAttention = {
        title: 'Test başlık',
        detail: 'Test detay',
        severity,
        href: '/ads',
      };
      expect(item.severity).toBe(severity);
    });
  });
});

describe('RolePriorityScreen type', () => {
  it('accepts a full priority screen payload', () => {
    const screen: RolePriorityScreen = {
      href: '/dashboard',
      label: 'Panel',
      why: 'Günlük performans takibi',
    };
    expect(screen.href).toBe('/dashboard');
    expect(screen.why).toBe('Günlük performans takibi');
  });
});

describe('RoleQuickAction type', () => {
  it('accepts a full quick action payload', () => {
    const action: RoleQuickAction = {
      label: 'Optimizasyon önerileri',
      href: '/optimizer',
    };
    expect(action.label).toBe('Optimizasyon önerileri');
    expect(action.href).toBe('/optimizer');
  });
});

describe('RoleKey type', () => {
  it('accepts all defined role keys', () => {
    const keys: RoleKey[] = [
      'performans',
      'marcom',
      'musteri_hizmetleri',
      'planlama',
      'yonetim',
    ];
    expect(keys).toHaveLength(5);
  });
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMockRoles(): RoleSummary[] {
  return [
    {
      key: 'performans',
      label: 'Performans Pazarlamacısı',
      description: 'Reklam harcamaları ve ROAS takibi.',
      icon_key: 'trending',
    },
    {
      key: 'marcom',
      label: 'Marka & İçerik (Marcom)',
      description: 'İçerik ve marka yönetimi.',
      icon_key: 'palette',
    },
  ];
}

function makeMockRoleView(): RoleView {
  return {
    role: 'performans',
    label: 'Performans Pazarlamacısı',
    description: 'Reklam harcamaları ve ROAS takibi.',
    icon_key: 'trending',
    generated_at: '2026-06-28T10:00:00Z',
    metrics: [
      { label: 'Harcama', value: '₺452.149', hint: 'Son 30 gün' },
      { label: 'ROAS', value: '4.2x', hint: 'Ortalama' },
    ],
    attention: [
      {
        title: 'Bütçe aşımı riski',
        detail: 'Meta kampanyası bütçeye yaklaşıyor.',
        severity: 'high',
        href: '/ads',
      },
      {
        title: 'Düşük CTR',
        detail: 'Google Search kampanyası ortalama altında.',
        severity: 'medium',
        href: '/ads',
      },
    ],
    priority_screens: [
      { href: '/dashboard', label: 'Panel', why: 'Günlük performans takibi' },
      { href: '/optimizer', label: 'Optimizasyon', why: 'Kampanya iyileştirme' },
    ],
    quick_actions: [
      { label: 'Optimizasyon önerileri', href: '/optimizer' },
      { label: 'Reklam yönetimi', href: '/ads' },
    ],
  };
}

// ---------------------------------------------------------------------------
// listRoles — fetch mock
// ---------------------------------------------------------------------------

describe('listRoles', () => {
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

  it('GETs /api/v1/role-views/roles', async () => {
    const mockResponse = makeMockRoles();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { listRoles } = await import('@/lib/role-views-api');
    const result = await listRoles();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/role-views/roles');
    expect(result).toHaveLength(2);
    expect(result[0].key).toBe('performans');
    expect(result[1].key).toBe('marcom');
  });

  it('parses the full RoleSummary array shape', async () => {
    const mockResponse = makeMockRoles();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { listRoles } = await import('@/lib/role-views-api');
    const result = await listRoles();

    expect(result[0].label).toBe('Performans Pazarlamacısı');
    expect(result[0].icon_key).toBe('trending');
    expect(result[1].icon_key).toBe('palette');
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse = makeMockRoles();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { listRoles } = await import('@/lib/role-views-api');
    await listRoles();

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

    const { listRoles } = await import('@/lib/role-views-api');
    await expect(listRoles()).rejects.toThrow('Sunucu hatası');
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

    const { listRoles } = await import('@/lib/role-views-api');
    await expect(listRoles()).rejects.toThrow('Oturum süresi doldu');
  });
});

// ---------------------------------------------------------------------------
// getRoleView — fetch mock
// ---------------------------------------------------------------------------

describe('getRoleView', () => {
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

  it('GETs /api/v1/role-views/{role} with the given role key', async () => {
    const mockResponse = makeMockRoleView();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getRoleView } = await import('@/lib/role-views-api');
    await getRoleView('performans');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/role-views/performans');
  });

  it('parses the full RoleView shape including metrics, attention, priority_screens, quick_actions', async () => {
    const mockResponse = makeMockRoleView();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getRoleView } = await import('@/lib/role-views-api');
    const result = await getRoleView('performans');

    expect(result.role).toBe('performans');
    expect(result.label).toBe('Performans Pazarlamacısı');
    expect(result.generated_at).toBe('2026-06-28T10:00:00Z');

    expect(result.metrics).toHaveLength(2);
    expect(result.metrics[0].label).toBe('Harcama');
    expect(result.metrics[0].value).toBe('₺452.149');
    expect(result.metrics[0].hint).toBe('Son 30 gün');

    expect(result.attention).toHaveLength(2);
    expect(result.attention[0].severity).toBe('high');
    expect(result.attention[0].href).toBe('/ads');
    expect(result.attention[1].severity).toBe('medium');

    expect(result.priority_screens).toHaveLength(2);
    expect(result.priority_screens[0].href).toBe('/dashboard');
    expect(result.priority_screens[0].why).toBe('Günlük performans takibi');

    expect(result.quick_actions).toHaveLength(2);
    expect(result.quick_actions[0].label).toBe('Optimizasyon önerileri');
    expect(result.quick_actions[0].href).toBe('/optimizer');
  });

  it('encodes the role with encodeURIComponent', async () => {
    const mockResponse = makeMockRoleView();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getRoleView } = await import('@/lib/role-views-api');
    // musteri_hizmetleri contains only URL-safe chars but let's test a space/special char
    await getRoleView('role with spaces');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('role%20with%20spaces');
    expect(url).not.toContain('role with spaces');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      text: () => Promise.resolve('Rol bulunamadı'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getRoleView } = await import('@/lib/role-views-api');
    await expect(getRoleView('bilinmeyen')).rejects.toThrow('Rol bulunamadı');
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

    const { getRoleView } = await import('@/lib/role-views-api');
    await expect(getRoleView('performans')).rejects.toThrow('Oturum süresi doldu');
  });
});
