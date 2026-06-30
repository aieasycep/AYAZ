// Notifications API — typed wrappers for /api/v1/notifications/*

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

  return res.json() as Promise<T>;
}

// --- Types ---

export type NotificationSeverity = 'info' | 'warning' | 'critical' | 'limit';

export interface NotificationOut {
  id: string;
  type: string;
  severity: NotificationSeverity;
  title: string;
  body: string;
  link: string | null;
  read: boolean;
  created_at: string;
}

export interface UnreadCountResponse {
  count: number;
}

export interface ReadAllResponse {
  updated: number;
}

// --- API functions ---

export async function getNotifications(
  unreadOnly = false,
  limit = 50,
): Promise<NotificationOut[]> {
  return authFetch<NotificationOut[]>(
    `/api/v1/notifications?unread_only=${unreadOnly}&limit=${limit}`,
  );
}

export async function getUnreadCount(): Promise<UnreadCountResponse> {
  return authFetch<UnreadCountResponse>('/api/v1/notifications/unread-count');
}

export async function markRead(id: string): Promise<NotificationOut> {
  return authFetch<NotificationOut>(`/api/v1/notifications/${id}/read`, {
    method: 'POST',
  });
}

export async function markAllRead(): Promise<ReadAllResponse> {
  return authFetch<ReadAllResponse>('/api/v1/notifications/read-all', {
    method: 'POST',
  });
}
