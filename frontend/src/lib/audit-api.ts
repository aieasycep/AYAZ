// Audit (Hesap Sağlık Taraması) API — typed wrappers for /api/v1/audit/*

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

  // DELETE / 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type AuditGrade = 'mukemmel' | 'iyi' | 'orta' | 'zayif';

export interface AuditCounts {
  pass: number;
  warn: number;
  fail: number;
}

export interface AuditCheck {
  id: string;
  severity: 'pass' | 'warn' | 'fail';
  title: string;
  finding: string;
  recommendation: string;
}

export interface AuditCategory {
  key: string;
  label: string;
  checks: AuditCheck[];
}

export interface AuditReport {
  score: number;
  grade: AuditGrade;
  summary: string;
  counts: AuditCounts;
  categories: AuditCategory[];
}

export const GRADE_LABELS: Record<AuditGrade, string> = {
  mukemmel: 'Mükemmel',
  iyi: 'İyi',
  orta: 'Orta',
  zayif: 'Zayıf',
};

// --- Audit API ---

export function runAudit(): Promise<AuditReport> {
  return authFetch<AuditReport>('/api/v1/audit/run');
}
