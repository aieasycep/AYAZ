// Benchmark API — typed wrappers for /api/v1/benchmark/*

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

export type BenchPosition = 'strong' | 'average' | 'weak';

export const POSITION_LABELS: Record<BenchPosition, string> = {
  strong: 'Güçlü',
  average: 'Ortalama',
  weak: 'Zayıf',
};

export interface BenchmarkMetric {
  key: string;
  label: string;
  unit: '%' | '₺' | 'x';
  your_value: number;
  ref_low: number;
  ref_mid: number;
  ref_high: number;
  higher_is_better: boolean;
  position: BenchPosition;
  verdict: string;
}

export interface BenchmarkChannel {
  channel: string;
  label: string;
  roas: number;
  ctr: number;
  roas_position: BenchPosition;
  ctr_position: BenchPosition;
}

export interface Benchmark {
  period: {
    date_from: string;
    date_to: string;
  };
  vertical: string;
  metrics: BenchmarkMetric[];
  channels: BenchmarkChannel[];
  headline: string;
  summary_counts: {
    strong: number;
    average: number;
    weak: number;
  };
}

// --- API function ---

export interface GetBenchmarkOptions {
  date_from?: string;
  date_to?: string;
}

export function getBenchmark(opts?: GetBenchmarkOptions): Promise<Benchmark> {
  const params = new URLSearchParams();
  if (opts?.date_from) params.set('date_from', opts.date_from);
  if (opts?.date_to) params.set('date_to', opts.date_to);
  const qs = params.toString();
  return authFetch<Benchmark>(
    `/api/v1/benchmark/overview${qs ? `?${qs}` : ''}`,
  );
}
