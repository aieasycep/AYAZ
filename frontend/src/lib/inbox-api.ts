// Sosyal Gelen Kutusu (Social Inbox) API — typed wrappers for /api/v1/inbox/*

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

  // DELETE / 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type Channel =
  | 'instagram'
  | 'facebook'
  | 'x'
  | 'linkedin'
  | 'tiktok'
  | 'youtube';

export type MessageKind = 'dm' | 'comment' | 'mention';

export type MessageStatus = 'open' | 'pending' | 'resolved' | 'snoozed';

export type Sentiment = 'positive' | 'neutral' | 'negative';

export interface SocialMessage {
  id: string;
  tenant_id: string;
  channel: Channel;
  kind: MessageKind;
  external_id: string;
  author_handle: string;
  author_name: string;
  text: string;
  permalink: string | null;
  sentiment: Sentiment;
  status: MessageStatus;
  assignee: string | null;
  tags: string[];
  received_at: string;
  created_at: string;
  updated_at: string;
}

export interface SocialReply {
  id: string;
  message_id: string;
  body: string;
  author: string;
  delivered: boolean;
  ai_assisted: boolean;
  created_at: string;
}

export interface MessageWithThread extends SocialMessage {
  replies: SocialReply[];
}

export interface InboxStats {
  total: number;
  by_status: Record<MessageStatus, number>;
  by_channel: Record<Channel, number>;
  by_sentiment: Record<Sentiment, number>;
  by_kind: Record<MessageKind, number>;
  open: number;
  pending: number;
  resolved: number;
}

// --- Label maps ---

export const CHANNEL_LABELS: Record<Channel, string> = {
  instagram: 'Instagram',
  facebook: 'Facebook',
  x: 'X (Twitter)',
  linkedin: 'LinkedIn',
  tiktok: 'TikTok',
  youtube: 'YouTube',
};

export const KIND_LABELS: Record<MessageKind, string> = {
  dm: 'Mesaj',
  comment: 'Yorum',
  mention: 'Bahsetme',
};

export const STATUS_LABELS: Record<MessageStatus, string> = {
  open: 'Açık',
  pending: 'Beklemede',
  resolved: 'Çözüldü',
  snoozed: 'Ertelendi',
};

export const SENTIMENT_LABELS: Record<Sentiment, string> = {
  positive: 'Olumlu',
  neutral: 'Nötr',
  negative: 'Olumsuz',
};

export const ALL_CHANNELS: Channel[] = [
  'instagram',
  'facebook',
  'x',
  'linkedin',
  'tiktok',
  'youtube',
];

export const ALL_STATUSES: MessageStatus[] = [
  'open',
  'pending',
  'resolved',
  'snoozed',
];

// --- API functions ---

export interface GetInboxMessagesOptions {
  channel?: Channel;
  kind?: MessageKind;
  status?: MessageStatus;
  sentiment?: Sentiment;
  assignee?: string;
}

export function getInboxMessages(
  opts: GetInboxMessagesOptions = {},
): Promise<SocialMessage[]> {
  const params = new URLSearchParams();
  if (opts.channel) params.set('channel', opts.channel);
  if (opts.kind) params.set('kind', opts.kind);
  if (opts.status) params.set('status', opts.status);
  if (opts.sentiment) params.set('sentiment', opts.sentiment);
  if (opts.assignee) params.set('assignee', opts.assignee);
  const qs = params.toString();
  return authFetch<SocialMessage[]>(
    `/api/v1/inbox/messages${qs ? `?${qs}` : ''}`,
  );
}

export interface CreateInboxMessagePayload {
  channel: Channel;
  kind: MessageKind;
  author_handle: string;
  text: string;
  author_name?: string;
  external_id?: string;
  permalink?: string;
  sentiment?: Sentiment;
  status?: MessageStatus;
  assignee?: string;
  tags?: string[];
}

export function createInboxMessage(
  payload: CreateInboxMessagePayload,
): Promise<SocialMessage> {
  return authFetch<SocialMessage>('/api/v1/inbox/messages', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getInboxMessage(id: string): Promise<MessageWithThread> {
  return authFetch<MessageWithThread>(`/api/v1/inbox/messages/${id}`);
}

export function deleteInboxMessage(id: string): Promise<void> {
  return authFetch<void>(`/api/v1/inbox/messages/${id}`, {
    method: 'DELETE',
  });
}

export function replyToMessage(
  id: string,
  body: string,
  author?: string,
): Promise<SocialReply> {
  return authFetch<SocialReply>(`/api/v1/inbox/messages/${id}/replies`, {
    method: 'POST',
    body: JSON.stringify({ body, ...(author ? { author } : {}) }),
  });
}

export function assignMessage(
  id: string,
  assignee: string,
): Promise<SocialMessage> {
  return authFetch<SocialMessage>(`/api/v1/inbox/messages/${id}/assign`, {
    method: 'POST',
    body: JSON.stringify({ assignee }),
  });
}

export function setMessageStatus(
  id: string,
  status: MessageStatus,
): Promise<SocialMessage> {
  return authFetch<SocialMessage>(`/api/v1/inbox/messages/${id}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });
}

export function setMessageTags(
  id: string,
  tags: string[],
): Promise<SocialMessage> {
  return authFetch<SocialMessage>(`/api/v1/inbox/messages/${id}/tags`, {
    method: 'POST',
    body: JSON.stringify({ tags }),
  });
}

export interface SuggestReplyOptions {
  text: string;
  channel?: Channel;
  tone?: string;
}

export interface SuggestReplyResult {
  reply: string;
  ai_assisted: boolean;
}

export function suggestReply(
  opts: SuggestReplyOptions,
): Promise<SuggestReplyResult> {
  return authFetch<SuggestReplyResult>('/api/v1/inbox/suggest-reply', {
    method: 'POST',
    body: JSON.stringify(opts),
  });
}

export function getInboxStats(): Promise<InboxStats> {
  return authFetch<InboxStats>('/api/v1/inbox/stats');
}
