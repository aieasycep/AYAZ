/**
 * Tests for the QuickAsk-related helper: createConversationWithMessage.
 *
 * We mock globalThis.fetch so we can test the orchestration logic
 * (create conversation → send first message → return conversation)
 * without hitting the network.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createConversationWithMessage } from '@/lib/assistant-api';

// jsdom bu ortamda native localStorage sağlamıyor (opaque origin); kod tabanının
// diğer testlerdeki kalıbına uyup localStorage'ı stub'lıyoruz — getToken buradan okur.
const fakeToken = 'test-token';

beforeEach(() => {
  vi.stubGlobal('localStorage', {
    getItem: (_key: string) => fakeToken,
    setItem: vi.fn(),
    removeItem: vi.fn(),
  });
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Build a minimal Response-like object that fetch would return. */
function makeFetchResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response;
}

describe('createConversationWithMessage', () => {
  it('creates a conversation then sends the first message, and returns the conversation', async () => {
    const fakeConv = {
      id: 'conv-123',
      title: 'Test',
      updated_at: new Date().toISOString(),
    };
    const fakeReply = {
      assistant_message: { role: 'assistant', content: 'Yanıt' },
      tools_used: [],
    };

    // First call → createConversation (POST /conversations)
    // Second call → sendMessage (POST /conversations/:id/messages)
    const mockFetch = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(makeFetchResponse(fakeConv))
      .mockResolvedValueOnce(makeFetchResponse(fakeReply));

    const result = await createConversationWithMessage('Merhaba');

    expect(result).toEqual(fakeConv);
    expect(mockFetch).toHaveBeenCalledTimes(2);

    // First call: create conversation
    const [createUrl, createOpts] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(createUrl).toContain('/api/v1/assistant/conversations');
    expect(createOpts.method).toBe('POST');

    // Second call: send message to the new conversation
    const [msgUrl, msgOpts] = mockFetch.mock.calls[1] as [string, RequestInit];
    expect(msgUrl).toContain(`/api/v1/assistant/conversations/conv-123/messages`);
    expect(msgOpts.method).toBe('POST');
    expect(JSON.parse(msgOpts.body as string)).toEqual({ content: 'Merhaba' });
  });

  it('propagates errors thrown by createConversation (non-ok response)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      makeFetchResponse({ detail: 'Sunucu hatası' }, 500),
    );

    await expect(
      createConversationWithMessage('Soru'),
    ).rejects.toThrow();
  });

  it('does not call sendMessage when createConversation rejects', async () => {
    const mockFetch = vi
      .spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new Error('Ağ hatası'));

    await expect(
      createConversationWithMessage('Soru'),
    ).rejects.toThrow('Ağ hatası');

    // fetch was only called once (the createConversation call)
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('propagates errors thrown by sendMessage', async () => {
    const fakeConv = {
      id: 'conv-456',
      title: null,
      updated_at: new Date().toISOString(),
    };

    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(makeFetchResponse(fakeConv))
      .mockRejectedValueOnce(new Error('Mesaj gönderilemedi'));

    await expect(
      createConversationWithMessage('Soru'),
    ).rejects.toThrow('Mesaj gönderilemedi');
  });
});
