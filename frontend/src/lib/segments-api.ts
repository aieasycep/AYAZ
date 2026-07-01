// Ürün/SKU Segment API — typed wrappers for /api/v1/segments/*

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

const TOKEN_KEY = 'ayaz_token';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

async function authFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
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
    const err = new Error(detail || 'İstek başarısız') as Error & { status?: number };
    err.status = res.status;
    throw err;
  }

  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}

// --- Types ---

export interface SegmentMetrics {
  units_sold: number;
  returned_units: number;
  gross_revenue: number;
  returned_revenue: number;
  net_revenue: number;
  ad_spend: number;
  gross_roas: number;
  net_roas: number;
  return_rate_pct: number;
}

export interface ProductRow extends SegmentMetrics {
  product_id: string;
  sku: string;
  name: string;
  category: string;
  price: number;
}

export interface CategoryRow extends SegmentMetrics {
  category: string;
  product_count: number;
}

export interface TotalsRow extends SegmentMetrics {
  product_count: number;
}

export interface ProductSegments {
  period: { date_from: string; date_to: string };
  currency: string;
  totals: TotalsRow;
  categories: CategoryRow[];
  products: ProductRow[];
}

// --- API function ---

export interface GetProductSegmentsOptions {
  date_from?: string;
  date_to?: string;
}

export function getProductSegments(
  opts?: GetProductSegmentsOptions,
): Promise<ProductSegments> {
  const params = new URLSearchParams();
  if (opts?.date_from) params.set('date_from', opts.date_from);
  if (opts?.date_to) params.set('date_to', opts.date_to);
  const qs = params.toString();
  return authFetch<ProductSegments>(
    `/api/v1/segments/products${qs ? `?${qs}` : ''}`,
  );
}
