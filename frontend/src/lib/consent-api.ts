// Consent Center API — typed wrappers for /api/v1/consent/center

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

  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export type ConsentGrade = 'uyumlu' | 'kismi' | 'eksik';
export type ConsentCheckStatus = 'pass' | 'warn' | 'fail';

export const GRADE_LABELS: Record<ConsentGrade, string> = {
  uyumlu: 'Uyumlu',
  kismi: 'Kısmi uyum',
  eksik: 'Eksik',
};

export interface ConsentSummary {
  total_events: number;
  consented_events: number;
  consent_rate_pct: number;
  skipped_no_consent: number;
  granular_supported: boolean;
}

export interface ConsentSignal {
  key: string;
  label: string;
  granted: number;
  denied: number;
  grant_rate_pct: number;
  description: string;
}

export interface ConsentDestination {
  name: string;
  platform: string;
  consent_required: boolean;
  required_consent: string[];
  forwarded: number;
  skipped_no_consent: number;
  posture_label: string;
}

export interface ConsentSource {
  name: string;
  consent_cookie_var: string;
  configured: boolean;
  events: number;
}

export interface ConsentCheck {
  id: string;
  label: string;
  status: ConsentCheckStatus;
  finding: string;
  recommendation: string;
}

export interface ConsentCompliance {
  score: number;
  grade: ConsentGrade;
  counts: {
    pass: number;
    warn: number;
    fail: number;
  };
  checks: ConsentCheck[];
}

export interface ConsentAuditEntry {
  event_time: string;
  event_name: string;
  consent: boolean;
  status: string;
  status_label: string;
  signals_summary: string;
}

export interface ConsentCenter {
  generated_at: string;
  period: {
    date_from: string;
    date_to: string;
  };
  summary: ConsentSummary;
  signals: ConsentSignal[];
  destinations: ConsentDestination[];
  sources: ConsentSource[];
  compliance: ConsentCompliance;
  audit_trail: ConsentAuditEntry[];
}

// --- API function ---

export function getConsentCenter(
  dateFrom?: string,
  dateTo?: string,
): Promise<ConsentCenter> {
  const params = new URLSearchParams();
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  const qs = params.toString();
  return authFetch<ConsentCenter>(
    `/api/v1/consent/center${qs ? `?${qs}` : ''}`,
  );
}
