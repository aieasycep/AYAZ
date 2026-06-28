// Onboarding (Kurulum Sihirbazı) API — typed wrappers for /api/v1/onboarding/*

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

  // DELETE / 204 No Content
  if (res.status === 204) return undefined as unknown as T;

  return res.json() as Promise<T>;
}

// --- Types ---

export interface OnboardingStep {
  key: string;
  title: string;
  description: string;
  done: boolean;
  cta_label: string;
  cta_link: string;
}

export interface OnboardingStatus {
  total_steps: number;
  completed_steps: number;
  percent: number;
  all_done: boolean;
  steps: OnboardingStep[];
}

// --- Onboarding API ---

export function getOnboardingStatus(): Promise<OnboardingStatus> {
  return authFetch<OnboardingStatus>('/api/v1/onboarding/status');
}
