import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  SocialMessage,
  SocialReply,
  MessageWithThread,
  InboxStats,
  Channel,
  MessageKind,
  MessageStatus,
  Sentiment,
} from '@/lib/inbox-api';
import {
  CHANNEL_LABELS,
  KIND_LABELS,
  STATUS_LABELS,
  SENTIMENT_LABELS,
  ALL_CHANNELS,
  ALL_STATUSES,
} from '@/lib/inbox-api';

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function stubLocalStorage(token = 'test-token') {
  vi.stubGlobal('localStorage', {
    getItem: (_key: string) => token,
    removeItem: vi.fn(),
    setItem: vi.fn(),
  });
}

function makeFetchMock<T>(payload: T, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(payload),
    text: () => Promise.resolve(JSON.stringify(payload)),
  });
}

function makeMessage(overrides: Partial<SocialMessage> = {}): SocialMessage {
  return {
    id: 'msg-1',
    tenant_id: 'ten-1',
    channel: 'instagram',
    kind: 'comment',
    external_id: 'ext-1',
    author_handle: 'test_user',
    author_name: 'Test User',
    text: 'Merhaba, bu bir test mesajıdır.',
    permalink: 'https://instagram.com/p/abc',
    sentiment: 'positive',
    status: 'open',
    assignee: null,
    tags: [],
    received_at: '2026-06-28T10:00:00Z',
    created_at: '2026-06-28T10:00:00Z',
    updated_at: '2026-06-28T10:00:00Z',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Label maps
// ---------------------------------------------------------------------------

describe('CHANNEL_LABELS', () => {
  it('maps all six channels to correct Turkish labels', () => {
    expect(CHANNEL_LABELS.instagram).toBe('Instagram');
    expect(CHANNEL_LABELS.facebook).toBe('Facebook');
    expect(CHANNEL_LABELS.x).toBe('X (Twitter)');
    expect(CHANNEL_LABELS.linkedin).toBe('LinkedIn');
    expect(CHANNEL_LABELS.tiktok).toBe('TikTok');
    expect(CHANNEL_LABELS.youtube).toBe('YouTube');
  });
});

describe('KIND_LABELS', () => {
  it('maps dm, comment, mention to Turkish', () => {
    expect(KIND_LABELS.dm).toBe('Mesaj');
    expect(KIND_LABELS.comment).toBe('Yorum');
    expect(KIND_LABELS.mention).toBe('Bahsetme');
  });
});

describe('STATUS_LABELS', () => {
  it('maps all four statuses to Turkish', () => {
    expect(STATUS_LABELS.open).toBe('Açık');
    expect(STATUS_LABELS.pending).toBe('Beklemede');
    expect(STATUS_LABELS.resolved).toBe('Çözüldü');
    expect(STATUS_LABELS.snoozed).toBe('Ertelendi');
  });
});

describe('SENTIMENT_LABELS', () => {
  it('maps sentiments to Turkish', () => {
    expect(SENTIMENT_LABELS.positive).toBe('Olumlu');
    expect(SENTIMENT_LABELS.neutral).toBe('Nötr');
    expect(SENTIMENT_LABELS.negative).toBe('Olumsuz');
  });
});

describe('ALL_CHANNELS and ALL_STATUSES', () => {
  it('ALL_CHANNELS contains all six channels', () => {
    const expected: Channel[] = ['instagram', 'facebook', 'x', 'linkedin', 'tiktok', 'youtube'];
    expect(ALL_CHANNELS).toEqual(expect.arrayContaining(expected));
    expect(ALL_CHANNELS).toHaveLength(6);
  });

  it('ALL_STATUSES contains all four statuses', () => {
    const expected: MessageStatus[] = ['open', 'pending', 'resolved', 'snoozed'];
    expect(ALL_STATUSES).toEqual(expect.arrayContaining(expected));
    expect(ALL_STATUSES).toHaveLength(4);
  });
});

// ---------------------------------------------------------------------------
// getInboxMessages — builds URL + query params
// ---------------------------------------------------------------------------

describe('getInboxMessages', () => {
  beforeEach(() => stubLocalStorage());
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('calls GET /api/v1/inbox/messages with no query string when no options given', async () => {
    const fetchMock = makeFetchMock<SocialMessage[]>([]);
    vi.stubGlobal('fetch', fetchMock);

    const { getInboxMessages } = await import('@/lib/inbox-api');
    await getInboxMessages();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/inbox/messages');
    expect(url).not.toContain('?');
  });

  it('appends channel and status query params when provided', async () => {
    const fetchMock = makeFetchMock<SocialMessage[]>([makeMessage()]);
    vi.stubGlobal('fetch', fetchMock);

    const { getInboxMessages } = await import('@/lib/inbox-api');
    await getInboxMessages({ channel: 'instagram', status: 'open' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('channel=instagram');
    expect(url).toContain('status=open');
  });

  it('appends kind, sentiment, and assignee filters', async () => {
    const fetchMock = makeFetchMock<SocialMessage[]>([]);
    vi.stubGlobal('fetch', fetchMock);

    const { getInboxMessages } = await import('@/lib/inbox-api');
    await getInboxMessages({ kind: 'dm', sentiment: 'negative', assignee: 'agent1' });

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('kind=dm');
    expect(url).toContain('sentiment=negative');
    expect(url).toContain('assignee=agent1');
  });

  it('sends Bearer token in Authorization header', async () => {
    const fetchMock = makeFetchMock<SocialMessage[]>([]);
    vi.stubGlobal('fetch', fetchMock);

    const { getInboxMessages } = await import('@/lib/inbox-api');
    await getInboxMessages();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
  });

  it('throws on non-ok response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getInboxMessages } = await import('@/lib/inbox-api');
    await expect(getInboxMessages()).rejects.toThrow('Sunucu hatası');
  });
});

// ---------------------------------------------------------------------------
// replyToMessage — POSTs body to /messages/{id}/replies
// ---------------------------------------------------------------------------

describe('replyToMessage', () => {
  beforeEach(() => stubLocalStorage());
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs body to /api/v1/inbox/messages/{id}/replies', async () => {
    const mockReply: SocialReply = {
      id: 'rep-1',
      message_id: 'msg-abc',
      body: 'Teşekkür ederiz!',
      author: 'agent',
      delivered: false,
      ai_assisted: false,
      created_at: '2026-06-28T11:00:00Z',
    };
    const fetchMock = makeFetchMock<SocialReply>(mockReply, 201);
    vi.stubGlobal('fetch', fetchMock);

    const { replyToMessage } = await import('@/lib/inbox-api');
    const result = await replyToMessage('msg-abc', 'Teşekkür ederiz!');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/inbox/messages/msg-abc/replies');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body as string)).toMatchObject({ body: 'Teşekkür ederiz!' });
    expect(result.id).toBe('rep-1');
    expect(result.delivered).toBe(false);
  });

  it('includes optional author in request body when provided', async () => {
    const mockReply: SocialReply = {
      id: 'rep-2',
      message_id: 'msg-xyz',
      body: 'Merhaba!',
      author: 'custom-agent',
      delivered: false,
      ai_assisted: false,
      created_at: '2026-06-28T11:30:00Z',
    };
    const fetchMock = makeFetchMock<SocialReply>(mockReply, 201);
    vi.stubGlobal('fetch', fetchMock);

    const { replyToMessage } = await import('@/lib/inbox-api');
    await replyToMessage('msg-xyz', 'Merhaba!', 'custom-agent');

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.author).toBe('custom-agent');
    expect(body.body).toBe('Merhaba!');
  });

  it('does not include author key when author is not provided', async () => {
    const mockReply: SocialReply = {
      id: 'rep-3',
      message_id: 'msg-1',
      body: 'Yanıt',
      author: 'system',
      delivered: false,
      ai_assisted: false,
      created_at: '2026-06-28T12:00:00Z',
    };
    const fetchMock = makeFetchMock<SocialReply>(mockReply, 201);
    vi.stubGlobal('fetch', fetchMock);

    const { replyToMessage } = await import('@/lib/inbox-api');
    await replyToMessage('msg-1', 'Yanıt');

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect('author' in body).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// suggestReply — returns parsed object
// ---------------------------------------------------------------------------

describe('suggestReply', () => {
  beforeEach(() => stubLocalStorage());
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs to /api/v1/inbox/suggest-reply and returns parsed result', async () => {
    const mockResult = { reply: 'Merhaba! Nasıl yardımcı olabilirim?', ai_assisted: true };
    const fetchMock = makeFetchMock(mockResult);
    vi.stubGlobal('fetch', fetchMock);

    const { suggestReply } = await import('@/lib/inbox-api');
    const result = await suggestReply({ text: 'sorunun cevabını bulabilir miyim?', channel: 'instagram' });

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/inbox/suggest-reply');
    expect(opts.method).toBe('POST');
    const body = JSON.parse(opts.body as string);
    expect(body.channel).toBe('instagram');
    expect(body.text).toBeTruthy();
    expect(result.reply).toBe('Merhaba! Nasıl yardımcı olabilirim?');
    expect(result.ai_assisted).toBe(true);
  });

  it('sends tone when provided', async () => {
    const mockResult = { reply: 'Üzgünüz...', ai_assisted: true };
    const fetchMock = makeFetchMock(mockResult);
    vi.stubGlobal('fetch', fetchMock);

    const { suggestReply } = await import('@/lib/inbox-api');
    await suggestReply({ text: 'kötü deneyim', tone: 'empathetic' });

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(opts.body as string);
    expect(body.tone).toBe('empathetic');
  });
});

// ---------------------------------------------------------------------------
// setMessageStatus — POSTs status
// ---------------------------------------------------------------------------

describe('setMessageStatus', () => {
  beforeEach(() => stubLocalStorage());
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs to /api/v1/inbox/messages/{id}/status with status in body', async () => {
    const updatedMsg = makeMessage({ id: 'msg-42', status: 'resolved' });
    const fetchMock = makeFetchMock<SocialMessage>(updatedMsg);
    vi.stubGlobal('fetch', fetchMock);

    const { setMessageStatus } = await import('@/lib/inbox-api');
    const result = await setMessageStatus('msg-42', 'resolved');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/inbox/messages/msg-42/status');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body as string)).toEqual({ status: 'resolved' });
    expect(result.status).toBe('resolved');
  });

  it('sends correct status for each valid value', async () => {
    const statuses: MessageStatus[] = ['open', 'pending', 'resolved', 'snoozed'];
    for (const status of statuses) {
      const fetchMock = makeFetchMock<SocialMessage>(makeMessage({ status }));
      vi.stubGlobal('fetch', fetchMock);

      const { setMessageStatus } = await import('@/lib/inbox-api');
      await setMessageStatus('msg-1', status);

      const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(JSON.parse(opts.body as string).status).toBe(status);

      vi.restoreAllMocks();
      vi.unstubAllGlobals();
      stubLocalStorage();
    }
  });
});

// ---------------------------------------------------------------------------
// getInboxStats — GETs stats
// ---------------------------------------------------------------------------

describe('getInboxStats', () => {
  beforeEach(() => stubLocalStorage());
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('GETs /api/v1/inbox/stats and returns parsed InboxStats', async () => {
    const mockStats: InboxStats = {
      total: 120,
      by_status: { open: 40, pending: 30, resolved: 45, snoozed: 5 },
      by_channel: { instagram: 50, facebook: 20, x: 15, linkedin: 10, tiktok: 15, youtube: 10 },
      by_sentiment: { positive: 60, neutral: 35, negative: 25 },
      by_kind: { dm: 30, comment: 50, mention: 40 },
      open: 40,
      pending: 30,
      resolved: 45,
    };
    const fetchMock = makeFetchMock<InboxStats>(mockStats);
    vi.stubGlobal('fetch', fetchMock);

    const { getInboxStats } = await import('@/lib/inbox-api');
    const result = await getInboxStats();

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/inbox/stats');
    // GET request — no body method override needed
    expect(opts?.method).toBeUndefined();
    expect(result.total).toBe(120);
    expect(result.open).toBe(40);
    expect(result.by_sentiment.positive).toBe(60);
    expect(result.by_channel.instagram).toBe(50);
  });

  it('throws on a non-ok stats response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve('Servis kullanılamıyor'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getInboxStats } = await import('@/lib/inbox-api');
    await expect(getInboxStats()).rejects.toThrow('Servis kullanılamıyor');
  });
});

// ---------------------------------------------------------------------------
// assignMessage — POSTs assignee
// ---------------------------------------------------------------------------

describe('assignMessage', () => {
  beforeEach(() => stubLocalStorage());
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs assignee to /api/v1/inbox/messages/{id}/assign', async () => {
    const updatedMsg = makeMessage({ assignee: 'agent007' });
    const fetchMock = makeFetchMock<SocialMessage>(updatedMsg);
    vi.stubGlobal('fetch', fetchMock);

    const { assignMessage } = await import('@/lib/inbox-api');
    const result = await assignMessage('msg-1', 'agent007');

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/inbox/messages/msg-1/assign');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body as string)).toEqual({ assignee: 'agent007' });
    expect(result.assignee).toBe('agent007');
  });
});

// ---------------------------------------------------------------------------
// setMessageTags — POSTs tags array
// ---------------------------------------------------------------------------

describe('setMessageTags', () => {
  beforeEach(() => stubLocalStorage());
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it('POSTs tags array to /api/v1/inbox/messages/{id}/tags', async () => {
    const updatedMsg = makeMessage({ tags: ['vip', 'urgent'] });
    const fetchMock = makeFetchMock<SocialMessage>(updatedMsg);
    vi.stubGlobal('fetch', fetchMock);

    const { setMessageTags } = await import('@/lib/inbox-api');
    const result = await setMessageTags('msg-1', ['vip', 'urgent']);

    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/inbox/messages/msg-1/tags');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body as string)).toEqual({ tags: ['vip', 'urgent'] });
    expect(result.tags).toEqual(['vip', 'urgent']);
  });
});

// ---------------------------------------------------------------------------
// Type contracts — SocialMessage and MessageWithThread
// ---------------------------------------------------------------------------

describe('SocialMessage type', () => {
  it('accepts a full message payload', () => {
    const msg: SocialMessage = makeMessage({
      id: 'msg-full',
      channel: 'facebook',
      kind: 'mention',
      sentiment: 'negative',
      status: 'pending',
      assignee: 'agent1',
      tags: ['complaint', 'priority'],
    });
    expect(msg.channel).toBe('facebook');
    expect(msg.kind).toBe('mention');
    expect(msg.sentiment).toBe('negative');
    expect(msg.tags).toHaveLength(2);
  });
});

describe('MessageWithThread type', () => {
  it('extends SocialMessage with a replies array', () => {
    const reply: SocialReply = {
      id: 'rep-1',
      message_id: 'msg-1',
      body: 'Yanıtlandı',
      author: 'destek',
      delivered: false,
      ai_assisted: true,
      created_at: '2026-06-28T12:00:00Z',
    };
    const thread: MessageWithThread = {
      ...makeMessage(),
      replies: [reply],
    };
    expect(thread.replies).toHaveLength(1);
    expect(thread.replies[0].ai_assisted).toBe(true);
    expect(thread.replies[0].delivered).toBe(false);
  });
});
