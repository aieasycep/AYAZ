// Integrations API — typed wrappers for /api/v1/integrations/*

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

export type IntegrationStatus =
  | 'connected'
  | 'connecting'
  | 'syncing'
  | 'needs_reconnect'
  | 'error'
  | 'disconnected';

export type IntegrationCategory =
  | 'ads'
  | 'analytics'
  | 'social'
  | 'messaging'
  | 'ecommerce'
  | 'productivity'
  | 'other';

export type AuthMode = 'oauth2' | 'oauth2_bundle' | 'api_key' | 'none';

export interface CatalogEntry {
  key: string;
  display_name: string;
  description: string;
  category: IntegrationCategory;
  auth_mode: AuthMode;
  icon: string;
  icon_bg: string;
  aliases: string[];
  coming_soon: boolean;
  min_plan: string;
  connected: boolean;           // tenant has at least one active connection
  connection_status?: IntegrationStatus; // populated when connected=true
  connection_id?: string;       // first/primary connection id when connected
}

export interface Connection {
  id: string;
  integration_key: string;
  display_name: string;
  status: IntegrationStatus;
  last_synced_at: string | null;
  capabilities: string[];
  scopes: string[];
}

export interface ConnectResponse {
  mode: 'popup' | 'api_key' | 'operator_setup_required';
  authorize_url?: string;       // present when mode='popup'
  connection_id?: string;
}

export interface ConnectApiKeyPayload {
  api_key: string;
  [key: string]: string;        // allow extra fields (api_secret, seller_id etc.)
}

// --- Helpers ---

export function statusLabel(status: IntegrationStatus): string {
  const labels: Record<IntegrationStatus, string> = {
    connected: 'Bağlı',
    connecting: 'Bağlanıyor',
    syncing: 'Senkronize ediliyor',
    needs_reconnect: 'Yeniden bağla',
    error: 'Hata',
    disconnected: 'Bağlı değil',
  };
  return labels[status];
}

// --- API functions ---

export function getCatalog(): Promise<CatalogEntry[]> {
  return authFetch<CatalogEntry[]>('/api/v1/integrations/catalog');
}

export function getConnections(): Promise<Connection[]> {
  return authFetch<Connection[]>('/api/v1/integrations/connections');
}

export function connectIntegration(key: string): Promise<ConnectResponse> {
  return authFetch<ConnectResponse>(`/api/v1/integrations/${key}/connect`, {
    method: 'POST',
  });
}

export function connectApiKey(
  key: string,
  payload: ConnectApiKeyPayload,
): Promise<Connection> {
  return authFetch<Connection>(`/api/v1/integrations/${key}/connect/api-key`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function disconnectIntegration(
  key: string,
  connectionId: string,
): Promise<void> {
  return authFetch<void>(
    `/api/v1/integrations/${key}/connections/${connectionId}`,
    { method: 'DELETE' },
  );
}

export function requestIntegration(key: string): Promise<void> {
  return authFetch<void>('/api/v1/integrations/requests', {
    method: 'POST',
    body: JSON.stringify({ integration_key: key }),
  });
}
