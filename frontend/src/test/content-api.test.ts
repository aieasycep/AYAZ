import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  ContentPost,
  ContentStatus,
  Channel,
  GenerateCaptionResult,
  PublishGatedResult,
} from '@/lib/content-api';
import {
  CHANNEL_LABELS,
  ALL_CHANNELS,
  STATUS_LABELS,
  STATUS_ORDER,
} from '@/lib/content-api';

// ---------------------------------------------------------------------------
// Label map constants
// ---------------------------------------------------------------------------

describe('CHANNEL_LABELS', () => {
  it('maps all six channels to Turkish/brand labels', () => {
    expect(CHANNEL_LABELS.instagram).toBe('Instagram');
    expect(CHANNEL_LABELS.facebook).toBe('Facebook');
    expect(CHANNEL_LABELS.x).toBe('X (Twitter)');
    expect(CHANNEL_LABELS.linkedin).toBe('LinkedIn');
    expect(CHANNEL_LABELS.tiktok).toBe('TikTok');
    expect(CHANNEL_LABELS.youtube).toBe('YouTube');
  });

  it('covers exactly six channels', () => {
    expect(Object.keys(CHANNEL_LABELS)).toHaveLength(6);
  });
});

describe('ALL_CHANNELS', () => {
  it('contains all six channel keys', () => {
    expect(ALL_CHANNELS).toHaveLength(6);
    const keys: Channel[] = ['instagram', 'facebook', 'x', 'linkedin', 'tiktok', 'youtube'];
    for (const k of keys) {
      expect(ALL_CHANNELS).toContain(k);
    }
  });
});

describe('STATUS_LABELS', () => {
  it('maps all six statuses to Turkish labels', () => {
    const labels: Record<ContentStatus, string> = {
      draft: 'Taslak',
      pending_approval: 'Onay Bekliyor',
      approved: 'Onaylandı',
      scheduled: 'Zamanlandı',
      published: 'Yayınlandı',
      archived: 'Arşiv',
    };
    for (const [status, label] of Object.entries(labels)) {
      expect(STATUS_LABELS[status as ContentStatus]).toBe(label);
    }
  });
});

describe('STATUS_ORDER', () => {
  it('contains exactly five board statuses in correct order', () => {
    expect(STATUS_ORDER).toEqual([
      'draft',
      'pending_approval',
      'approved',
      'scheduled',
      'published',
    ]);
  });

  it('does not include archived', () => {
    expect(STATUS_ORDER).not.toContain('archived');
  });
});

// ---------------------------------------------------------------------------
// ContentPost type contract
// ---------------------------------------------------------------------------

describe('ContentPost type', () => {
  it('accepts a full post payload', () => {
    const post: ContentPost = {
      id: 'p-001',
      tenant_id: 't-1',
      title: 'Yaz Kampanyası',
      body: 'Yaz kampanyamız başladı!',
      channels: ['instagram', 'facebook'],
      scheduled_at: '2026-07-01T10:00:00Z',
      status: 'scheduled',
      approval_note: null,
      media_url: 'https://cdn.example.com/img.jpg',
      ai_assisted: true,
      created_at: '2026-06-28T08:00:00Z',
      updated_at: '2026-06-28T09:00:00Z',
    };
    expect(post.title).toBe('Yaz Kampanyası');
    expect(post.channels).toContain('instagram');
    expect(post.ai_assisted).toBe(true);
    expect(post.status).toBe('scheduled');
  });

  it('accepts a minimal draft post', () => {
    const post: ContentPost = {
      id: 'p-002',
      tenant_id: 't-1',
      title: 'Taslak',
      body: null,
      channels: [],
      scheduled_at: null,
      status: 'draft',
      approval_note: null,
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T08:00:00Z',
      updated_at: '2026-06-28T08:00:00Z',
    };
    expect(post.status).toBe('draft');
    expect(post.body).toBeNull();
    expect(post.ai_assisted).toBe(false);
  });
});

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
// getContentPosts — URL and query string construction
// ---------------------------------------------------------------------------

describe('getContentPosts', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls GET /api/v1/content/posts with no query string when called with no options', async () => {
    const mockPosts: ContentPost[] = [];
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPosts),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getContentPosts } = await import('@/lib/content-api');
    const result = await getContentPosts();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/posts');
    expect(url).not.toContain('?');
    expect(result).toEqual([]);
  });

  it('appends status query parameter when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getContentPosts } = await import('@/lib/content-api');
    await getContentPosts({ status: 'draft' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('status=draft');
  });

  it('appends channel query parameter when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getContentPosts } = await import('@/lib/content-api');
    await getContentPosts({ channel: 'instagram' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('channel=instagram');
  });

  it('appends date_from and date_to when both provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getContentPosts } = await import('@/lib/content-api');
    await getContentPosts({ date_from: '2026-06-01', date_to: '2026-06-30' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).toContain('date_to=2026-06-30');
  });

  it('sends Bearer token in Authorization header', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
      text: () => Promise.resolve('[]'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getContentPosts } = await import('@/lib/content-api');
    await getContentPosts();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getContentPosts } = await import('@/lib/content-api');
    await expect(getContentPosts()).rejects.toThrow('Sunucu hatası');
  });
});

// ---------------------------------------------------------------------------
// createContentPost — POST body
// ---------------------------------------------------------------------------

describe('createContentPost', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('POSTs to /api/v1/content/posts and returns the created post', async () => {
    const mockPost: ContentPost = {
      id: 'new-001',
      tenant_id: 't-1',
      title: 'Test İçerik',
      body: 'Açıklama metni',
      channels: ['instagram'],
      scheduled_at: null,
      status: 'draft',
      approval_note: null,
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:00:00Z',
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { createContentPost } = await import('@/lib/content-api');
    const result = await createContentPost({
      title: 'Test İçerik',
      body: 'Açıklama metni',
      channels: ['instagram'],
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/posts');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.title).toBe('Test İçerik');
    expect(body.body).toBe('Açıklama metni');
    expect(body.channels).toEqual(['instagram']);
    expect(result.id).toBe('new-001');
    expect(result.status).toBe('draft');
  });

  it('sends scheduled_at and media_url when provided', async () => {
    const mockPost: ContentPost = {
      id: 'new-002',
      tenant_id: 't-1',
      title: 'Zamanlanmış',
      body: null,
      channels: ['linkedin'],
      scheduled_at: '2026-07-01T09:00:00Z',
      status: 'draft',
      approval_note: null,
      media_url: 'https://cdn.example.com/img.png',
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:00:00Z',
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { createContentPost } = await import('@/lib/content-api');
    await createContentPost({
      title: 'Zamanlanmış',
      channels: ['linkedin'],
      scheduled_at: '2026-07-01T09:00:00Z',
      media_url: 'https://cdn.example.com/img.png',
    });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.scheduled_at).toBe('2026-07-01T09:00:00Z');
    expect(body.media_url).toBe('https://cdn.example.com/img.png');
  });
});

// ---------------------------------------------------------------------------
// generateCaption — AI caption helper
// ---------------------------------------------------------------------------

describe('generateCaption', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('POSTs to /api/v1/content/ai-caption and returns parsed result', async () => {
    const mockResult: GenerateCaptionResult = {
      caption: 'Yazın tadını çıkarın! Bu yaz en iyi fırsatlar sizi bekliyor.',
      hashtags: ['#yaz', '#kampanya', '#indirim'],
      ai_assisted: true,
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResult),
      text: () => Promise.resolve(JSON.stringify(mockResult)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { generateCaption } = await import('@/lib/content-api');
    const result = await generateCaption({
      brief: 'Yaz kampanyamız için Instagram açıklaması',
      channel: 'instagram',
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/ai-caption');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.brief).toBe('Yaz kampanyamız için Instagram açıklaması');
    expect(body.channel).toBe('instagram');
    expect(result.caption).toBe(
      'Yazın tadını çıkarın! Bu yaz en iyi fırsatlar sizi bekliyor.',
    );
    expect(result.hashtags).toEqual(['#yaz', '#kampanya', '#indirim']);
    expect(result.ai_assisted).toBe(true);
  });

  it('includes optional tone field when provided', async () => {
    const mockResult: GenerateCaptionResult = {
      caption: 'Profesyonel bir mesaj.',
      hashtags: [],
      ai_assisted: true,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResult),
      text: () => Promise.resolve(JSON.stringify(mockResult)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { generateCaption } = await import('@/lib/content-api');
    await generateCaption({
      brief: 'Ürün lansmanı',
      tone: 'professional',
    });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.tone).toBe('professional');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve('AI servisi kullanılamıyor'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { generateCaption } = await import('@/lib/content-api');
    await expect(
      generateCaption({ brief: 'Test' }),
    ).rejects.toThrow('AI servisi kullanılamıyor');
  });
});

// ---------------------------------------------------------------------------
// publishPost — 501 credential gate (must NOT throw)
// ---------------------------------------------------------------------------

describe('publishPost', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('returns {gated: true, message} on a 501 response instead of throwing', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 501,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve('Not Implemented'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { publishPost } = await import('@/lib/content-api');
    const result = await publishPost('post-abc');

    expect(fetchMock).toHaveBeenCalledOnce();
    const gated = result as PublishGatedResult;
    expect(gated.gated).toBe(true);
    expect(typeof gated.message).toBe('string');
    expect(gated.message.length).toBeGreaterThan(10);
  });

  it('does not throw on 501 (gated check)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 501,
      text: () => Promise.resolve('Not Implemented'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { publishPost } = await import('@/lib/content-api');
    // Must resolve (not reject)
    await expect(publishPost('post-xyz')).resolves.not.toThrow();
  });

  it('throws on other non-ok errors (e.g. 500)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { publishPost } = await import('@/lib/content-api');
    await expect(publishPost('post-err')).rejects.toThrow('Sunucu hatası');
  });

  it('calls POST /api/v1/content/posts/{id}/publish with Bearer token', async () => {
    const mockPost: ContentPost = {
      id: 'post-pub',
      tenant_id: 't-1',
      title: 'Yayınlanan İçerik',
      body: null,
      channels: ['facebook'],
      scheduled_at: null,
      status: 'published',
      approval_note: null,
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:00:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { publishPost } = await import('@/lib/content-api');
    const result = await publishPost('post-pub');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/posts/post-pub/publish');
    expect(opts.method).toBe('POST');
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    // On 200, returns the post (not gated)
    const post = result as ContentPost;
    expect(post.id).toBe('post-pub');
  });
});

// ---------------------------------------------------------------------------
// submitPost, approvePost, rejectPost, schedulePost — fetch mocks
// ---------------------------------------------------------------------------

describe('submitPost', () => {
  beforeEach(stubLocalStorage);
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs to /api/v1/content/posts/{id}/submit and returns the updated post', async () => {
    const mockPost: ContentPost = {
      id: 'p-1',
      tenant_id: 't-1',
      title: 'Gönderildi',
      body: null,
      channels: [],
      scheduled_at: null,
      status: 'pending_approval',
      approval_note: null,
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:01:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { submitPost } = await import('@/lib/content-api');
    const result = await submitPost('p-1');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/posts/p-1/submit');
    expect(opts.method).toBe('POST');
    expect(result.status).toBe('pending_approval');
  });
});

describe('approvePost', () => {
  beforeEach(stubLocalStorage);
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs to /api/v1/content/posts/{id}/approve and returns approved post', async () => {
    const mockPost: ContentPost = {
      id: 'p-2',
      tenant_id: 't-1',
      title: 'Onaylandı',
      body: null,
      channels: [],
      scheduled_at: null,
      status: 'approved',
      approval_note: null,
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:02:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { approvePost } = await import('@/lib/content-api');
    const result = await approvePost('p-2');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/posts/p-2/approve');
    expect(opts.method).toBe('POST');
    expect(result.status).toBe('approved');
  });
});

describe('rejectPost', () => {
  beforeEach(stubLocalStorage);
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs to /api/v1/content/posts/{id}/reject with optional note', async () => {
    const mockPost: ContentPost = {
      id: 'p-3',
      tenant_id: 't-1',
      title: 'Reddedildi',
      body: null,
      channels: [],
      scheduled_at: null,
      status: 'draft',
      approval_note: 'Görsel eksik.',
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:03:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { rejectPost } = await import('@/lib/content-api');
    const result = await rejectPost('p-3', 'Görsel eksik.');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/posts/p-3/reject');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.note).toBe('Görsel eksik.');
    expect(result.status).toBe('draft');
    expect(result.approval_note).toBe('Görsel eksik.');
  });

  it('sends empty object when no note provided', async () => {
    const mockPost: ContentPost = {
      id: 'p-4',
      tenant_id: 't-1',
      title: 'Reddedildi (not yok)',
      body: null,
      channels: [],
      scheduled_at: null,
      status: 'draft',
      approval_note: null,
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:04:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { rejectPost } = await import('@/lib/content-api');
    await rejectPost('p-4');

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.note).toBeUndefined();
  });
});

describe('schedulePost', () => {
  beforeEach(stubLocalStorage);
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs to /api/v1/content/posts/{id}/schedule with scheduled_at in body', async () => {
    const scheduledAt = '2026-07-15T14:00:00Z';
    const mockPost: ContentPost = {
      id: 'p-5',
      tenant_id: 't-1',
      title: 'Zamanlandı',
      body: null,
      channels: ['tiktok'],
      scheduled_at: scheduledAt,
      status: 'scheduled',
      approval_note: null,
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:05:00Z',
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { schedulePost } = await import('@/lib/content-api');
    const result = await schedulePost('p-5', scheduledAt);

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/posts/p-5/schedule');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.scheduled_at).toBe(scheduledAt);
    expect(result.status).toBe('scheduled');
    expect(result.scheduled_at).toBe(scheduledAt);
  });
});

// ---------------------------------------------------------------------------
// createFromCreative — Kreatif → İçerik köprüsü
// ---------------------------------------------------------------------------

describe('createFromCreative', () => {
  beforeEach(stubLocalStorage);

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('POSTs ad context to /api/v1/content/from-creative and returns a draft', async () => {
    const mockPost: ContentPost = {
      id: 'cr-001',
      tenant_id: 't-1',
      title: 'Yaz İndirimi',
      body: 'Samimi bir dille: Yaz İndirimi\n\n#yaz #indirim',
      channels: ['instagram', 'facebook'],
      scheduled_at: null,
      status: 'draft',
      approval_note: null,
      media_url: null,
      ai_assisted: false,
      created_at: '2026-06-28T10:00:00Z',
      updated_at: '2026-06-28T10:00:00Z',
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve(mockPost),
      text: () => Promise.resolve(JSON.stringify(mockPost)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { createFromCreative } = await import('@/lib/content-api');
    const result = await createFromCreative({
      ad_name: 'Yaz İndirimi - Karusel',
      campaign_name: 'Yaz Kampanyası',
      channel: 'meta',
      tone: 'samimi',
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/content/from-creative');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.ad_name).toBe('Yaz İndirimi - Karusel');
    expect(body.channel).toBe('meta');
    expect(result.status).toBe('draft');
    expect(result.channels).toEqual(['instagram', 'facebook']);
  });
});
