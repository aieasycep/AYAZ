import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { HealthIndex, HealthDimension, HealthSummary, HealthGrade, DimensionStatus } from '@/lib/health-index-api';
import { GRADE_LABELS } from '@/lib/health-index-api';

// ---------------------------------------------------------------------------
// GRADE_LABELS constant
// ---------------------------------------------------------------------------

describe('GRADE_LABELS', () => {
  it('maps all four grades to correct Turkish labels', () => {
    expect(GRADE_LABELS.mukemmel).toBe('Mükemmel');
    expect(GRADE_LABELS.iyi).toBe('İyi');
    expect(GRADE_LABELS.orta).toBe('Orta');
    expect(GRADE_LABELS.zayif).toBe('Zayıf');
  });

  it('covers exactly the four HealthGrade values', () => {
    const keys = Object.keys(GRADE_LABELS) as HealthGrade[];
    expect(keys).toHaveLength(4);
    expect(keys).toContain('mukemmel');
    expect(keys).toContain('iyi');
    expect(keys).toContain('orta');
    expect(keys).toContain('zayif');
  });
});

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('HealthDimension type', () => {
  it('accepts a scored dimension', () => {
    const dim: HealthDimension = {
      key: 'hesap_sagligi',
      label: 'Hesap Sağlığı',
      score: 60,
      grade: 'orta',
      status: 'ok',
      detail: 'Hesap sağlık taraması: 60/100',
      href: '/audit',
      weight: 1,
    };
    expect(dim.key).toBe('hesap_sagligi');
    expect(dim.score).toBe(60);
    expect(dim.grade).toBe('orta');
    expect(dim.status).toBe('ok');
  });

  it('accepts a veri_yok dimension with null score and grade', () => {
    const dim: HealthDimension = {
      key: 'hedef_ilerleme',
      label: 'Hedef İlerleme',
      score: null,
      grade: null,
      status: 'veri_yok',
      detail: 'Tanımlı hedef yok',
      href: '/goals',
      weight: 1,
    };
    expect(dim.score).toBeNull();
    expect(dim.grade).toBeNull();
    expect(dim.status).toBe('veri_yok');
  });
});

describe('HealthSummary type', () => {
  it('accepts a full summary payload', () => {
    const summary: HealthSummary = {
      strong_count: 3,
      weak_count: 0,
      scored_count: 5,
    };
    expect(summary.strong_count).toBe(3);
    expect(summary.weak_count).toBe(0);
    expect(summary.scored_count).toBe(5);
  });
});

// ---------------------------------------------------------------------------
// Helpers for building mock response
// ---------------------------------------------------------------------------

function makeMockHealthIndex(): HealthIndex {
  return {
    generated_at: '2026-06-29T10:00:00Z',
    overall_score: 74,
    overall_grade: 'iyi',
    dimensions: [
      {
        key: 'hesap_sagligi',
        label: 'Hesap Sağlığı',
        score: 60,
        grade: 'orta',
        status: 'ok',
        detail: 'Hesap sağlık taraması: 60/100',
        href: '/audit',
        weight: 1,
      },
      {
        key: 'sektor_konumu',
        label: 'Sektör Konumu',
        score: 60,
        grade: 'orta',
        status: 'ok',
        detail: 'Sektör konumu taraması: 60/100',
        href: '/benchmark',
        weight: 1,
      },
      {
        key: 'kvkk_uyum',
        label: 'KVKK Uyumu',
        score: 100,
        grade: 'mukemmel',
        status: 'ok',
        detail: 'KVKK uyumu eksiksiz',
        href: '/consent',
        weight: 1,
      },
      {
        key: 'donusum',
        label: 'Dönüşüm',
        score: 100,
        grade: 'mukemmel',
        status: 'ok',
        detail: 'Dönüşüm hedefleri karşılandı',
        href: '/funnel',
        weight: 1,
      },
      {
        key: 'hedef_ilerleme',
        label: 'Hedef İlerleme',
        score: null,
        grade: null,
        status: 'veri_yok',
        detail: 'Tanımlı hedef yok',
        href: '/goals',
        weight: 1,
      },
      {
        key: 'butce_disiplini',
        label: 'Bütçe Disiplini',
        score: 96,
        grade: 'mukemmel',
        status: 'ok',
        detail: 'Bütçe disiplini mükemmel',
        href: '/planning',
        weight: 1,
      },
    ],
    summary: {
      strong_count: 3,
      weak_count: 0,
      scored_count: 5,
    },
  };
}

// ---------------------------------------------------------------------------
// getHealthIndex — fetch mock
// ---------------------------------------------------------------------------

describe('getHealthIndex', () => {
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

  it('GETs /api/v1/health-index', async () => {
    const mockResponse = makeMockHealthIndex();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getHealthIndex } = await import('@/lib/health-index-api');
    const result = await getHealthIndex();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/health-index');
    expect(result.overall_score).toBe(74);
    expect(result.overall_grade).toBe('iyi');
  });

  it('parses overall_score, overall_grade, and generated_at', async () => {
    const mockResponse = makeMockHealthIndex();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getHealthIndex } = await import('@/lib/health-index-api');
    const result = await getHealthIndex();

    expect(result.overall_score).toBe(74);
    expect(result.overall_grade).toBe('iyi');
    expect(result.generated_at).toBe('2026-06-29T10:00:00Z');
  });

  it('parses all 6 dimensions including the null-score veri_yok dimension', async () => {
    const mockResponse = makeMockHealthIndex();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getHealthIndex } = await import('@/lib/health-index-api');
    const result = await getHealthIndex();

    expect(result.dimensions).toHaveLength(6);

    const hedef = result.dimensions.find((d) => d.key === 'hedef_ilerleme');
    expect(hedef).toBeDefined();
    expect(hedef!.score).toBeNull();
    expect(hedef!.grade).toBeNull();
    expect(hedef!.status).toBe('veri_yok');
    expect(hedef!.detail).toBe('Tanımlı hedef yok');

    const kvkk = result.dimensions.find((d) => d.key === 'kvkk_uyum');
    expect(kvkk).toBeDefined();
    expect(kvkk!.score).toBe(100);
    expect(kvkk!.grade).toBe('mukemmel');
    expect(kvkk!.status).toBe('ok');
  });

  it('parses summary counts correctly', async () => {
    const mockResponse = makeMockHealthIndex();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getHealthIndex } = await import('@/lib/health-index-api');
    const result = await getHealthIndex();

    expect(result.summary.strong_count).toBe(3);
    expect(result.summary.weak_count).toBe(0);
    expect(result.summary.scored_count).toBe(5);
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse = makeMockHealthIndex();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getHealthIndex } = await import('@/lib/health-index-api');
    await getHealthIndex();

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

    const { getHealthIndex } = await import('@/lib/health-index-api');
    await expect(getHealthIndex()).rejects.toThrow('Sunucu hatası');
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

    const { getHealthIndex } = await import('@/lib/health-index-api');
    await expect(getHealthIndex()).rejects.toThrow('Oturum süresi doldu');
  });
});
