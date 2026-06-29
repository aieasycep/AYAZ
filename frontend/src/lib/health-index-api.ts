// Health Index API — typed wrappers for /api/v1/health-index

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

export type HealthGrade = 'mukemmel' | 'iyi' | 'orta' | 'zayif';
export type DimensionStatus = 'ok' | 'veri_yok';

export const GRADE_LABELS: Record<HealthGrade, string> = {
  mukemmel: 'Mükemmel',
  iyi: 'İyi',
  orta: 'Orta',
  zayif: 'Zayıf',
};

export interface HealthDimension {
  key: string;
  label: string;
  score: number | null;
  grade: HealthGrade | null;
  status: DimensionStatus;
  detail: string;
  href: string;
  weight: number;
}

export interface HealthSummary {
  strong_count: number;
  weak_count: number;
  scored_count: number;
}

export interface HealthIndex {
  generated_at: string;
  overall_score: number;
  overall_grade: HealthGrade;
  dimensions: HealthDimension[];
  summary: HealthSummary;
}

// --- API functions ---

export function getHealthIndex(): Promise<HealthIndex> {
  return authFetch<HealthIndex>('/api/v1/health-index');
}
