// Attribution API — typed wrappers for /api/v1/attribution/*
//
// Kaynak-mutabakatı (Google Ads/Meta Ads "platform-claimed" dönüşümler vs
// GA4'ün gerçek/tek-kaynak-doğrusu dönüşümleri) özetini döner. Bkz. backend
// ayaz/services/attribution.py + ayaz/api/v1/attribution.py docstring'leri.

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

/** "ad" = harcaması olan reklam platformu; "analytics" = harcamasız ölçüm kaynağı (GA4, Search Console). */
export type AttributionSourceType = 'ad' | 'analytics';

export interface AttributionChannelRow {
  key: string;
  label: string;
  source_type: AttributionSourceType;
  spend: number;
  conversions: number;
  conversion_value: number;
  /** Kanalın KENDİ ROAS'ı (spend==0 iken anlamsızdır — arayüzde "—" göster). */
  roas: number;
}

export interface AttributionSummary {
  date_from: string;
  date_to: string;
  /** Reklam platformlarının (google_ads+meta_ads) kendi iddia ettiği toplam dönüşüm. */
  platform_claimed_conversions: number;
  platform_claimed_revenue: number;
  /** GA4'ün ölçtüğü — tek-kaynak-doğrusu — gerçek dönüşüm. */
  ga4_conversions: number;
  ga4_revenue: number;
  /** platform_claimed / ga4 — GA4 verisi yoksa/sıfırsa null (karşılaştırma anlamsız). */
  inflation_factor: number | null;
  /** Yalnız reklam harcaması (analitik kaynaklar harcama taşımaz). */
  ad_spend: number;
  /** ga4_revenue / ad_spend — de-duplike, "gerçek" ROAS. GA4 yoksa/sıfırsa 0. */
  blended_roas: number;
  channels: AttributionChannelRow[];
}

// --- API function ---

/** days: 1-90 (backend `Query(..., ge=1, le=90)`); varsayılan 30. */
export function getAttributionSummary(days = 30): Promise<AttributionSummary> {
  return authFetch<AttributionSummary>(
    `/api/v1/attribution/summary?days=${encodeURIComponent(String(days))}`,
  );
}
