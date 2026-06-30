// Workspaces API — typed wrappers for /api/v1/workspaces/*

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

const TOKEN_KEY = 'ayaz_token';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, token);
  }
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

  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type WorkspaceRole = 'owner' | 'admin' | 'member';

export interface Workspace {
  id: string;
  name: string;
  role: WorkspaceRole;
  brand_name: string | null;
  logo_url: string | null;
  primary_color: string | null;
}

export interface WorkspaceMember {
  membership_id: string;
  email: string;
  role: WorkspaceRole;
}

export interface SwitchTokenResponse {
  access_token: string;
  token_type: string;
  tenant_id: string;
}

export interface WhiteLabelSettings {
  brand_name: string | null;
  logo_url: string | null;
  primary_color: string | null;
}

// --- API functions ---

export function getWorkspaces(): Promise<Workspace[]> {
  return authFetch<Workspace[]>('/api/v1/workspaces');
}

export function createWorkspace(name: string): Promise<Workspace> {
  return authFetch<Workspace>('/api/v1/workspaces', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

export function switchWorkspace(tenant_id: string): Promise<SwitchTokenResponse> {
  return authFetch<SwitchTokenResponse>('/api/v1/workspaces/switch', {
    method: 'POST',
    body: JSON.stringify({ tenant_id }),
  });
}

export function getCurrentWorkspace(): Promise<Workspace> {
  return authFetch<Workspace>('/api/v1/workspaces/current');
}

export function patchCurrentWorkspace(payload: Partial<WhiteLabelSettings>): Promise<Workspace> {
  return authFetch<Workspace>('/api/v1/workspaces/current', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function getMembers(): Promise<WorkspaceMember[]> {
  return authFetch<WorkspaceMember[]>('/api/v1/workspaces/members');
}

export function inviteMember(email: string, role: WorkspaceRole): Promise<void> {
  return authFetch<void>('/api/v1/workspaces/invitations', {
    method: 'POST',
    body: JSON.stringify({ email, role }),
  });
}

export function removeMember(membership_id: string): Promise<void> {
  return authFetch<void>(`/api/v1/workspaces/members/${membership_id}`, {
    method: 'DELETE',
  });
}

export function patchMember(membership_id: string, role: WorkspaceRole): Promise<WorkspaceMember> {
  return authFetch<WorkspaceMember>(`/api/v1/workspaces/members/${membership_id}`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
}
