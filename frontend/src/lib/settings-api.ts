// Account & Settings API — typed wrappers for /api/v1/auth/*

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
    // For change-password 429 pass through to callers with a known status code;
    // attach it to the error object so the page can show a specific message.
    const bodyText = await res.text().catch(() => '');
    let detail = '';
    try {
      const parsed = JSON.parse(bodyText);
      // FastAPI validation errors (422) arrive as { detail: [ { msg, ... } ] }
      if (Array.isArray(parsed.detail)) {
        detail = parsed.detail.map((e: { msg?: string }) => e.msg ?? '').join(', ');
        if (!detail) detail = 'Yeni şifre geçersiz.';
      } else {
        detail = parsed.detail ?? '';
      }
    } catch {
      detail = bodyText;
    }
    const err = new Error(detail || 'İstek başarısız') as Error & { status?: number };
    err.status = res.status;
    throw err;
  }

  return res.json() as Promise<T>;
}

// --- Types ---

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  created_at: string | null;
}

export interface UpdateProfilePayload {
  full_name?: string;
  email?: string;
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
}

export interface UserPreferences {
  locale: 'tr' | 'en';
  timezone: string;
  email_alerts: boolean;
  email_briefing: boolean;
}

export type UpdatePreferencesPayload = Partial<UserPreferences>;

// --- API functions ---

export function getMe(): Promise<UserProfile> {
  return authFetch<UserProfile>('/api/v1/auth/me');
}

export function updateProfile(payload: UpdateProfilePayload): Promise<UserProfile> {
  return authFetch<UserProfile>('/api/v1/auth/me', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function changePassword(
  payload: ChangePasswordPayload,
): Promise<{ detail: string }> {
  return authFetch<{ detail: string }>('/api/v1/auth/change-password', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getPreferences(): Promise<UserPreferences> {
  return authFetch<UserPreferences>('/api/v1/auth/preferences');
}

export function updatePreferences(
  payload: UpdatePreferencesPayload,
): Promise<UserPreferences> {
  return authFetch<UserPreferences>('/api/v1/auth/preferences', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}
