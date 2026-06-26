// Assistant / Copilot API — typed wrappers for /api/v1/assistant/*

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

const TOKEN_KEY = 'ayaz_token';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

async function authFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const url = `${API_BASE}${path}`;

  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token ?? ''}`,
      ...options?.headers,
    },
  });

  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = '/login';
    }
    throw new Error('Oturum süresi doldu');
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => 'İstek başarısız');
    throw new Error(detail || 'İstek başarısız');
  }

  // DELETE and similar may return 204 with no body
  const text = await res.text();
  if (!text) return undefined as unknown as T;
  return JSON.parse(text) as T;
}

// --- Types ---

export interface Conversation {
  id: string;
  title: string;
  updated_at: string;
}

export type MessageRole = 'user' | 'assistant';

export interface ToolUsed {
  name: string;
  summary: string;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  tool_name: string | null;
  created_at: string;
}

export interface SendMessageResponse {
  assistant_message: {
    role: MessageRole;
    content: string;
  };
  tools_used: ToolUsed[];
}

// --- API ---

export function listConversations(): Promise<Conversation[]> {
  return authFetch<Conversation[]>('/api/v1/assistant/conversations');
}

export function createConversation(): Promise<Conversation> {
  return authFetch<Conversation>('/api/v1/assistant/conversations', {
    method: 'POST',
    body: JSON.stringify({}),
  });
}

export function getMessages(conversationId: string): Promise<Message[]> {
  return authFetch<Message[]>(
    `/api/v1/assistant/conversations/${conversationId}/messages`,
  );
}

export function sendMessage(
  conversationId: string,
  content: string,
): Promise<SendMessageResponse> {
  return authFetch<SendMessageResponse>(
    `/api/v1/assistant/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      body: JSON.stringify({ content }),
    },
  );
}
