import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  AdPlatform,
  AdTone,
  AdField,
  AdVariant,
  AdGenerateRequest,
  AdGenerateResult,
  AdCopyDraft,
  DraftStatus,
} from '@/lib/ad-studio-api';
import { PLATFORM_LABELS, TONE_LABELS } from '@/lib/ad-studio-api';

// ---------------------------------------------------------------------------
// Label maps
// ---------------------------------------------------------------------------

describe('PLATFORM_LABELS', () => {
  it('maps all three platforms to correct Turkish labels', () => {
    expect(PLATFORM_LABELS.google_ads).toBe('Google Ads');
    expect(PLATFORM_LABELS.meta_ads).toBe('Meta (Facebook/Instagram)');
    expect(PLATFORM_LABELS.tiktok_ads).toBe('TikTok');
  });

  it('covers exactly the three AdPlatform values', () => {
    const keys = Object.keys(PLATFORM_LABELS) as AdPlatform[];
    expect(keys).toHaveLength(3);
    expect(keys).toContain('google_ads');
    expect(keys).toContain('meta_ads');
    expect(keys).toContain('tiktok_ads');
  });
});

describe('TONE_LABELS', () => {
  it('maps all four tones to correct Turkish labels', () => {
    expect(TONE_LABELS.profesyonel).toBe('Profesyonel');
    expect(TONE_LABELS.samimi).toBe('Samimi');
    expect(TONE_LABELS.heyecanli).toBe('Heyecanlı');
    expect(TONE_LABELS.bilgilendirici).toBe('Bilgilendirici');
  });

  it('covers exactly the four AdTone values', () => {
    const keys = Object.keys(TONE_LABELS) as AdTone[];
    expect(keys).toHaveLength(4);
    expect(keys).toContain('profesyonel');
    expect(keys).toContain('samimi');
    expect(keys).toContain('heyecanli');
    expect(keys).toContain('bilgilendirici');
  });
});

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('AdField type', () => {
  it('accepts a full field payload', () => {
    const field: AdField = {
      key: 'primary_text',
      label: 'Ana Metin',
      value: 'Ürününüzü keşfedin.',
      char_count: 22,
      max_len: 125,
      within_limit: true,
    };
    expect(field.key).toBe('primary_text');
    expect(field.within_limit).toBe(true);
  });
});

describe('AdVariant type', () => {
  it('accepts a variant with fields', () => {
    const variant: AdVariant = {
      index: 0,
      fields: [
        {
          key: 'headline',
          label: 'Başlık',
          value: 'Harika Fırsatlar',
          char_count: 16,
          max_len: 40,
          within_limit: true,
        },
      ],
    };
    expect(variant.index).toBe(0);
    expect(variant.fields).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Shared mock helpers
// ---------------------------------------------------------------------------

function makeAdField(overrides?: Partial<AdField>): AdField {
  return {
    key: 'primary_text',
    label: 'Ana Metin',
    value: 'Test metin içeriği',
    char_count: 18,
    max_len: 125,
    within_limit: true,
    ...overrides,
  };
}

function makeAdVariant(index = 0): AdVariant {
  return {
    index,
    fields: [
      makeAdField({ key: 'primary_text', label: 'Ana Metin' }),
      makeAdField({ key: 'headline', label: 'Başlık', value: 'Test Başlık', char_count: 11, max_len: 40 }),
    ],
  };
}

function makeMockGenerateResult(): AdGenerateResult {
  return {
    platform: 'meta_ads',
    platform_label: 'Meta (Facebook/Instagram)',
    source: 'template',
    tone: 'profesyonel',
    tone_label: 'Profesyonel',
    variants: [makeAdVariant(0), makeAdVariant(1)],
  };
}

function makeMockDraft(): AdCopyDraft {
  return {
    id: 'draft-001',
    platform: 'meta_ads',
    platform_label: 'Meta (Facebook/Instagram)',
    title: 'Kablosuz Kulaklık',
    brief: {
      platform: 'meta_ads',
      product: 'Kablosuz Kulaklık',
    },
    variants: [makeAdVariant(0)],
    source: 'template',
    status: 'saved',
    created_at: '2026-06-28T10:00:00Z',
    updated_at: '2026-06-28T10:00:00Z',
  };
}

function makeOkResponse<T>(data: T) {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  };
}

// ---------------------------------------------------------------------------
// generateAdCopy
// ---------------------------------------------------------------------------

describe('generateAdCopy', () => {
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

  it('POSTs to /api/v1/ad-studio/generate with correct body', async () => {
    const mockResponse = makeMockGenerateResult();
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(mockResponse));
    vi.stubGlobal('fetch', fetchMock);

    const { generateAdCopy } = await import('@/lib/ad-studio-api');
    const req: AdGenerateRequest = {
      platform: 'meta_ads',
      product: 'Kablosuz Kulaklık',
      tone: 'profesyonel',
      n_variants: 2,
    };
    await generateAdCopy(req);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/ad-studio/generate');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.platform).toBe('meta_ads');
    expect(body.product).toBe('Kablosuz Kulaklık');
    expect(body.tone).toBe('profesyonel');
    expect(body.n_variants).toBe(2);
  });

  it('parses variants and fields from the response', async () => {
    const mockResponse = makeMockGenerateResult();
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(mockResponse));
    vi.stubGlobal('fetch', fetchMock);

    const { generateAdCopy } = await import('@/lib/ad-studio-api');
    const result = await generateAdCopy({ platform: 'meta_ads', product: 'Test' });

    expect(result.platform).toBe('meta_ads');
    expect(result.platform_label).toBe('Meta (Facebook/Instagram)');
    expect(result.source).toBe('template');
    expect(result.variants).toHaveLength(2);
    expect(result.variants[0].fields).toHaveLength(2);
    expect(result.variants[0].fields[0].key).toBe('primary_text');
    expect(result.variants[0].fields[0].within_limit).toBe(true);
  });

  it('sends Bearer token in Authorization header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(makeMockGenerateResult()));
    vi.stubGlobal('fetch', fetchMock);

    const { generateAdCopy } = await import('@/lib/ad-studio-api');
    await generateAdCopy({ platform: 'google_ads', product: 'Test' });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
  });

  it('includes keywords array in body when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(makeMockGenerateResult()));
    vi.stubGlobal('fetch', fetchMock);

    const { generateAdCopy } = await import('@/lib/ad-studio-api');
    await generateAdCopy({ platform: 'tiktok_ads', product: 'Test', keywords: ['kampanya', 'indirim'] });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.keywords).toEqual(['kampanya', 'indirim']);
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { generateAdCopy } = await import('@/lib/ad-studio-api');
    await expect(generateAdCopy({ platform: 'meta_ads', product: 'Test' })).rejects.toThrow('Sunucu hatası');
  });
});

// ---------------------------------------------------------------------------
// saveDraft
// ---------------------------------------------------------------------------

describe('saveDraft', () => {
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

  it('POSTs to /api/v1/ad-studio/drafts with correct body', async () => {
    const mockDraft = makeMockDraft();
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(mockDraft));
    vi.stubGlobal('fetch', fetchMock);

    const { saveDraft } = await import('@/lib/ad-studio-api');
    await saveDraft({
      platform: 'meta_ads',
      title: 'Kablosuz Kulaklık',
      brief: { platform: 'meta_ads', product: 'Kablosuz Kulaklık' },
      variants: [makeAdVariant(0)],
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/ad-studio/drafts');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.platform).toBe('meta_ads');
    expect(body.title).toBe('Kablosuz Kulaklık');
  });

  it('parses the returned draft', async () => {
    const mockDraft = makeMockDraft();
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(mockDraft));
    vi.stubGlobal('fetch', fetchMock);

    const { saveDraft } = await import('@/lib/ad-studio-api');
    const result = await saveDraft({
      platform: 'meta_ads',
      title: 'Kablosuz Kulaklık',
      brief: { platform: 'meta_ads', product: 'Kablosuz Kulaklık' },
      variants: [makeAdVariant(0)],
    });

    expect(result.id).toBe('draft-001');
    expect(result.status).toBe('saved');
    expect(result.platform_label).toBe('Meta (Facebook/Instagram)');
  });
});

// ---------------------------------------------------------------------------
// listDrafts
// ---------------------------------------------------------------------------

describe('listDrafts', () => {
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

  it('GETs /api/v1/ad-studio/drafts without query string when no status given', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse([makeMockDraft()]));
    vi.stubGlobal('fetch', fetchMock);

    const { listDrafts } = await import('@/lib/ad-studio-api');
    await listDrafts();

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/ad-studio/drafts');
    expect(url).not.toContain('?status=');
  });

  it('appends ?status=saved when status is "saved"', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse([makeMockDraft()]));
    vi.stubGlobal('fetch', fetchMock);

    const { listDrafts } = await import('@/lib/ad-studio-api');
    await listDrafts('saved');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('?status=saved');
  });

  it('appends ?status=archived when status is "archived"', async () => {
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse([]));
    vi.stubGlobal('fetch', fetchMock);

    const { listDrafts } = await import('@/lib/ad-studio-api');
    await listDrafts('archived' as DraftStatus);

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('?status=archived');
  });

  it('returns an array of drafts', async () => {
    const drafts = [makeMockDraft(), { ...makeMockDraft(), id: 'draft-002' }];
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(drafts));
    vi.stubGlobal('fetch', fetchMock);

    const { listDrafts } = await import('@/lib/ad-studio-api');
    const result = await listDrafts();

    expect(result).toHaveLength(2);
    expect(result[0].id).toBe('draft-001');
  });
});

// ---------------------------------------------------------------------------
// updateDraftStatus
// ---------------------------------------------------------------------------

describe('updateDraftStatus', () => {
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

  it('PATCHes /api/v1/ad-studio/drafts/{id} with correct status body', async () => {
    const updated = { ...makeMockDraft(), status: 'archived' as DraftStatus };
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(updated));
    vi.stubGlobal('fetch', fetchMock);

    const { updateDraftStatus } = await import('@/lib/ad-studio-api');
    await updateDraftStatus('draft-001', 'archived');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/ad-studio/drafts/draft-001');
    expect(opts.method).toBe('PATCH');
    const body = JSON.parse(opts.body as string);
    expect(body.status).toBe('archived');
  });

  it('returns the updated draft', async () => {
    const updated = { ...makeMockDraft(), status: 'archived' as DraftStatus };
    const fetchMock = vi.fn().mockResolvedValue(makeOkResponse(updated));
    vi.stubGlobal('fetch', fetchMock);

    const { updateDraftStatus } = await import('@/lib/ad-studio-api');
    const result = await updateDraftStatus('draft-001', 'archived');

    expect(result.status).toBe('archived');
  });
});

// ---------------------------------------------------------------------------
// deleteDraft — 204 no body
// ---------------------------------------------------------------------------

describe('deleteDraft', () => {
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

  it('DELETEs /api/v1/ad-studio/drafts/{id}', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: () => { throw new Error('Should not call json() on 204'); },
      text: () => Promise.resolve(''),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { deleteDraft } = await import('@/lib/ad-studio-api');
    await deleteDraft('draft-001');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/ad-studio/drafts/draft-001');
    expect(opts.method).toBe('DELETE');
  });

  it('resolves with undefined on 204 without calling json()', async () => {
    const jsonSpy = vi.fn().mockRejectedValue(new Error('Should not call json() on 204'));
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: jsonSpy,
      text: () => Promise.resolve(''),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { deleteDraft } = await import('@/lib/ad-studio-api');
    const result = await deleteDraft('draft-002');

    expect(result).toBeUndefined();
    expect(jsonSpy).not.toHaveBeenCalled();
  });

  it('throws when server returns non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      text: () => Promise.resolve('Taslak bulunamadi'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { deleteDraft } = await import('@/lib/ad-studio-api');
    await expect(deleteDraft('nonexistent')).rejects.toThrow('Taslak bulunamadi');
  });
});

// ---------------------------------------------------------------------------
// error path — 401 redirect
// ---------------------------------------------------------------------------

describe('authFetch 401 handling', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
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

    const { listDrafts } = await import('@/lib/ad-studio-api');
    await expect(listDrafts()).rejects.toThrow('Oturum süresi doldu');
  });
});
