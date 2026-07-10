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
    // Attach the HTTP status so callers (parseApiError) can distinguish
    // server errors (5xx) from client errors (4xx) without string-matching.
    const err = new Error(detail || 'İstek başarısız') as Error & { status?: number };
    err.status = res.status;
    throw err;
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
  external_account_id: string;
  display_name: string;
  sync_status: SyncStatus;
  watermark: string | null; // ISO date string of last sync
}

export interface AuthorizeResponse {
  authorize_url: string;
}

// --- API functions ---

// Backend SyncStatus enum is {idle, syncing, success, error, paused}; the UI
// switches on {connected, syncing, error, pending}. Map to the UI vocabulary
// so badges/labels render correctly.
const SYNC_STATUS_MAP: Record<string, SyncStatus> = {
  idle: 'pending',
  syncing: 'syncing',
  success: 'connected',
  connected: 'connected',
  error: 'error',
  paused: 'pending',
  pending: 'pending',
};

function normaliseAccount(a: ConnectedAccount): ConnectedAccount {
  if (a && a.sync_status) {
    a.sync_status = SYNC_STATUS_MAP[a.sync_status as string] ?? a.sync_status;
  }
  return a;
}

export async function getConnectedAccounts(): Promise<ConnectedAccount[]> {
  const accounts = await authFetch<ConnectedAccount[]>(
    '/api/v1/connectors/accounts',
  );
  return accounts.map(normaliseAccount);
}

export function getOAuthAuthorizeUrl(platform: Platform): Promise<AuthorizeResponse> {
  return authFetch<AuthorizeResponse>(`/api/v1/oauth/${platform}/authorize`);
}

export interface SyncResult {
  status: string;
  account_id: string;
  inserted: number;
  updated: number;
  records_processed: number;
}

/**
 * Trigger a synchronous data sync for one connected account.
 * Runs in the request (no background worker on the current deployment).
 * Default mirrors the backend's default backfill window (90 days); callers
 * doing a first-ever sync for an account should pass a larger window (e.g.
 * 365) since the account may have no recent data yet.
 */
export function syncAccount(accountId: string, days = 90): Promise<SyncResult> {
  return authFetch<SyncResult>(
    `/api/v1/connectors/accounts/${accountId}/sync?days=${days}`,
    { method: 'POST' },
  );
}

export interface DiscoveredAccount {
  id: string;
  name: string;
  currency: string;
}

/** List the ad accounts reachable with this connection's stored credentials. */
export function discoverAccounts(accountId: string): Promise<DiscoveredAccount[]> {
  return authFetch<DiscoveredAccount[]>(
    `/api/v1/connectors/accounts/${accountId}/discover`,
    { method: 'POST' },
  );
}

/** Update a connected account (e.g. set the ad account id after OAuth). */
export async function updateAccount(
  accountId: string,
  body: { external_account_id?: string; display_name?: string },
): Promise<ConnectedAccount> {
  const acc = await authFetch<ConnectedAccount>(
    `/api/v1/connectors/accounts/${accountId}`,
    { method: 'PATCH', body: JSON.stringify(body) },
  );
  return normaliseAccount(acc);
}
