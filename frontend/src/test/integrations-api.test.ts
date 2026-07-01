import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  CatalogEntry,
  Connection,
  ConnectResponse,
  IntegrationStatus,
} from '@/lib/integrations-api';

// ---------------------------------------------------------------------------
// Shared mock factory helpers
// ---------------------------------------------------------------------------

function makeCatalogEntry(overrides: Partial<CatalogEntry> = {}): CatalogEntry {
  return {
    key: 'meta_ads',
    display_name: 'Meta Ads',
    description: 'Meta reklam hesabınızı bağlayın.',
    category: 'ads',
    auth_mode: 'oauth2',
    icon: 'meta.svg',
    icon_bg: '#1877F2',
    aliases: ['facebook_ads'],
    coming_soon: false,
    min_plan: 'free',
    connected: false,
    ...overrides,
  };
}

function makeConnection(overrides: Partial<Connection> = {}): Connection {
  return {
    id: 'conn-123',
    integration_key: 'meta_ads',
    display_name: 'Meta Ads – İşletme Hesabı',
    status: 'connected',
    last_synced_at: '2026-06-30T10:00:00Z',
    capabilities: ['ads', 'insights'],
    scopes: ['ads_read', 'ads_management'],
    ...overrides,
  };
}

function okResponse(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  };
}

function stubLocalStorage(token = 'test-token') {
  vi.stubGlobal('localStorage', {
    getItem: (_key: string) => token,
    removeItem: vi.fn(),
    setItem: vi.fn(),
  });
}

// ---------------------------------------------------------------------------
// getCatalog
// ---------------------------------------------------------------------------

describe('getCatalog', () => {
  beforeEach(() => {
    stubLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls GET /api/v1/integrations/catalog and returns CatalogEntry[]', async () => {
    const mockData: CatalogEntry[] = [
      makeCatalogEntry(),
      makeCatalogEntry({ key: 'google_ads', display_name: 'Google Ads', connected: true }),
    ];

    const fetchMock = vi.fn().mockResolvedValue(okResponse(mockData));
    vi.stubGlobal('fetch', fetchMock);

    const { getCatalog } = await import('@/lib/integrations-api');
    const result = await getCatalog();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/integrations/catalog');
    expect(result).toHaveLength(2);
    expect(result[0].key).toBe('meta_ads');
    expect(result[1].connected).toBe(true);
  });

  it('sends Authorization Bearer header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse([]));
    vi.stubGlobal('fetch', fetchMock);

    const { getCatalog } = await import('@/lib/integrations-api');
    await getCatalog();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
  });
});

// ---------------------------------------------------------------------------
// getConnections
// ---------------------------------------------------------------------------

describe('getConnections', () => {
  beforeEach(() => {
    stubLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls GET /api/v1/integrations/connections and returns Connection[]', async () => {
    const mockData: Connection[] = [makeConnection(), makeConnection({ id: 'conn-456', status: 'syncing' })];

    const fetchMock = vi.fn().mockResolvedValue(okResponse(mockData));
    vi.stubGlobal('fetch', fetchMock);

    const { getConnections } = await import('@/lib/integrations-api');
    const result = await getConnections();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/integrations/connections');
    expect(result).toHaveLength(2);
    expect(result[1].status).toBe('syncing');
  });
});

// ---------------------------------------------------------------------------
// connectIntegration
// ---------------------------------------------------------------------------

describe('connectIntegration', () => {
  beforeEach(() => {
    stubLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls POST /api/v1/integrations/{key}/connect and returns mode=popup with authorize_url', async () => {
    const mockResp: ConnectResponse = {
      mode: 'popup',
      authorize_url: 'https://www.facebook.com/dialog/oauth?client_id=123',
    };

    const fetchMock = vi.fn().mockResolvedValue(okResponse(mockResp));
    vi.stubGlobal('fetch', fetchMock);

    const { connectIntegration } = await import('@/lib/integrations-api');
    const result = await connectIntegration('meta_ads');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/integrations/meta_ads/connect');
    expect(opts.method).toBe('POST');
    expect(result.mode).toBe('popup');
    expect(result.authorize_url).toBe('https://www.facebook.com/dialog/oauth?client_id=123');
  });

  it('returns mode=api_key when no authorize_url', async () => {
    const mockResp: ConnectResponse = { mode: 'api_key' };

    const fetchMock = vi.fn().mockResolvedValue(okResponse(mockResp));
    vi.stubGlobal('fetch', fetchMock);

    const { connectIntegration } = await import('@/lib/integrations-api');
    const result = await connectIntegration('custom_tool');

    expect(result.mode).toBe('api_key');
    expect(result.authorize_url).toBeUndefined();
  });

  it('returns mode=operator_setup_required', async () => {
    const mockResp: ConnectResponse = { mode: 'operator_setup_required' };

    const fetchMock = vi.fn().mockResolvedValue(okResponse(mockResp));
    vi.stubGlobal('fetch', fetchMock);

    const { connectIntegration } = await import('@/lib/integrations-api');
    const result = await connectIntegration('enterprise_tool');

    expect(result.mode).toBe('operator_setup_required');
  });
});

// ---------------------------------------------------------------------------
// connectApiKey
// ---------------------------------------------------------------------------

describe('connectApiKey', () => {
  beforeEach(() => {
    stubLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls POST /api/v1/integrations/{key}/connect/api-key with payload in body', async () => {
    const mockConn = makeConnection({ integration_key: 'klaviyo', status: 'connected' });

    const fetchMock = vi.fn().mockResolvedValue(okResponse(mockConn));
    vi.stubGlobal('fetch', fetchMock);

    const { connectApiKey } = await import('@/lib/integrations-api');
    const payload = { api_key: 'pk_live_abc123', api_secret: 'sk_live_xyz' };
    const result = await connectApiKey('klaviyo', payload);

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/integrations/klaviyo/connect/api-key');
    expect(opts.method).toBe('POST');

    const body = JSON.parse(opts.body as string);
    expect(body.api_key).toBe('pk_live_abc123');
    expect(body.api_secret).toBe('sk_live_xyz');

    expect(result.integration_key).toBe('klaviyo');
    expect(result.status).toBe('connected');
  });

  it('sends Content-Type application/json on POST requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse(makeConnection()));
    vi.stubGlobal('fetch', fetchMock);

    const { connectApiKey } = await import('@/lib/integrations-api');
    await connectApiKey('klaviyo', { api_key: 'key123' });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
  });
});

// ---------------------------------------------------------------------------
// disconnectIntegration
// ---------------------------------------------------------------------------

describe('disconnectIntegration', () => {
  beforeEach(() => {
    stubLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls DELETE /api/v1/integrations/{key}/connections/{id}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: () => Promise.resolve(undefined),
      text: () => Promise.resolve(''),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { disconnectIntegration } = await import('@/lib/integrations-api');
    await disconnectIntegration('meta_ads', 'conn-123');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/integrations/meta_ads/connections/conn-123');
    expect(opts.method).toBe('DELETE');
  });
});

// ---------------------------------------------------------------------------
// requestIntegration
// ---------------------------------------------------------------------------

describe('requestIntegration', () => {
  beforeEach(() => {
    stubLocalStorage();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls POST /api/v1/integrations/requests with {integration_key: key}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(''),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { requestIntegration } = await import('@/lib/integrations-api');
    await requestIntegration('tiktok_ads');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/integrations/requests');
    expect(opts.method).toBe('POST');

    const body = JSON.parse(opts.body as string);
    expect(body).toEqual({ integration_key: 'tiktok_ads' });
  });

  it('sends Content-Type application/json', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(''),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { requestIntegration } = await import('@/lib/integrations-api');
    await requestIntegration('snapchat_ads');

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Content-Type']).toBe('application/json');
  });
});

// ---------------------------------------------------------------------------
// 401 handling — throws Turkish session-expired error
// ---------------------------------------------------------------------------

describe('401 handling', () => {
  beforeEach(() => {
    stubLocalStorage();

    const mockLocation = { href: '' };
    Object.defineProperty(globalThis, 'window', {
      value: { location: mockLocation, localStorage: globalThis.localStorage },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('throws "Oturum süresi doldu" on 401 from getCatalog', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getCatalog } = await import('@/lib/integrations-api');
    await expect(getCatalog()).rejects.toThrow('Oturum süresi doldu');
  });

  it('throws "Oturum süresi doldu" on 401 from connectIntegration', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { connectIntegration } = await import('@/lib/integrations-api');
    await expect(connectIntegration('meta_ads')).rejects.toThrow('Oturum süresi doldu');
  });

  it('throws "Oturum süresi doldu" on 401 from disconnectIntegration', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { disconnectIntegration } = await import('@/lib/integrations-api');
    await expect(disconnectIntegration('meta_ads', 'conn-1')).rejects.toThrow('Oturum süresi doldu');
  });
});

// ---------------------------------------------------------------------------
// statusLabel
// ---------------------------------------------------------------------------

describe('statusLabel', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('maps every IntegrationStatus to the correct Turkish string', async () => {
    const { statusLabel } = await import('@/lib/integrations-api');

    const cases: Array<[IntegrationStatus, string]> = [
      ['connected', 'Bağlı'],
      ['connecting', 'Bağlanıyor'],
      ['syncing', 'Senkronize ediliyor'],
      ['needs_reconnect', 'Yeniden bağla'],
      ['error', 'Hata'],
      ['disconnected', 'Bağlı değil'],
    ];

    for (const [status, expected] of cases) {
      expect(statusLabel(status)).toBe(expected);
    }
  });

  it('returns "Bağlı" for connected', async () => {
    const { statusLabel } = await import('@/lib/integrations-api');
    expect(statusLabel('connected')).toBe('Bağlı');
  });

  it('returns "Hata" for error', async () => {
    const { statusLabel } = await import('@/lib/integrations-api');
    expect(statusLabel('error')).toBe('Hata');
  });

  it('returns "Yeniden bağla" for needs_reconnect', async () => {
    const { statusLabel } = await import('@/lib/integrations-api');
    expect(statusLabel('needs_reconnect')).toBe('Yeniden bağla');
  });
});
