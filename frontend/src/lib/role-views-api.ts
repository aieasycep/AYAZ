// Role Views API — typed wrappers for /api/v1/role-views/*

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

  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type RoleKey =
  | 'performans'
  | 'marcom'
  | 'musteri_hizmetleri'
  | 'planlama'
  | 'yonetim';

export type AttentionSeverity = 'high' | 'medium' | 'low';

export interface RoleSummary {
  key: string;
  label: string;
  description: string;
  icon_key: string;
}

export interface RoleMetric {
  label: string;
  value: string;
  hint: string;
}

export interface RoleAttention {
  title: string;
  detail: string;
  severity: AttentionSeverity;
  href: string;
}

export interface RolePriorityScreen {
  href: string;
  label: string;
  why: string;
}

export interface RoleQuickAction {
  label: string;
  href: string;
}

export interface RoleView {
  role: string;
  label: string;
  description: string;
  icon_key: string;
  generated_at: string;
  metrics: RoleMetric[];
  attention: RoleAttention[];
  priority_screens: RolePriorityScreen[];
  quick_actions: RoleQuickAction[];
}

// --- API functions ---

export function listRoles(): Promise<RoleSummary[]> {
  return authFetch<RoleSummary[]>('/api/v1/role-views/roles');
}

export function getRoleView(role: string): Promise<RoleView> {
  const encodedRole = encodeURIComponent(role);
  return authFetch<RoleView>(`/api/v1/role-views/${encodedRole}`);
}
