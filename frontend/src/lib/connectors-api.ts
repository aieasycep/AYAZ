// Connectors & OAuth API — typed wrappers for /api/v1/connectors and /api/v1/oauth

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

export type SyncStatus = 'connected' | 'syncing' | 'error' | 'pending';

export type Platform =
  | 'google_ads'
  | 'meta_ads'
  | 'ga4'
  | 'search_console'
  | 'tiktok_ads'
  | 'linkedin_ads'
  | 'microsoft_ads'
  | 'criteo'
  | 'pinterest_ads';

export interface ConnectedAccount {
  id: string;
  platform: Platform;
  display_name: string;
  sync_status: SyncStatus;
  watermark: string | null; // ISO date string of last sync
}

export interface AuthorizeResponse {
  authorize_url: string;
}

// --- API functions ---

export function getConnectedAccounts(): Promise<ConnectedAccount[]> {
  return authFetch<ConnectedAccount[]>('/api/v1/connectors/accounts');
}

export function getOAuthAuthorizeUrl(platform: Platform): Promise<AuthorizeResponse> {
  return authFetch<AuthorizeResponse>(`/api/v1/oauth/${platform}/authorize`);
}
