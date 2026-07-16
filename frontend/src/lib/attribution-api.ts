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

/** GA4 bağlantı/ölçüm kalitesi — şişme faktörü ve blended ROAS'ın güvenilirliği için. */
export interface AttributionDataQuality {
  /** analytics-source (GA4) herhangi bir satır var mı. */
  ga4_connected: boolean;
  /** Ücretli kanal-grubu (Paid Search/Paid Social/...) GA4 satırı var mı. */
  ga4_paid_tracked: boolean;
  /** Doldurulduğunda arayüzde amber uyarı banner'ı olarak gösterilir. */
  note: string | null;
}

export interface AttributionSummary {
  date_from: string;
  date_to: string;
  /** Reklam platformlarının (google_ads+meta_ads) kendi iddia ettiği toplam dönüşüm. */
  platform_claimed_conversions: number;
  platform_claimed_revenue: number;
  /** GA4'ün ölçtüğü TOPLAM dönüşüm/gelir — tüm kanal grupları (organik+direkt dahil). */
  ga4_conversions: number;
  ga4_revenue: number;
  /** Yalnız ücretli kanal-grubu (Paid Search/Paid Social/...) GA4 satırları — reklam
   *  platformu iddialarıyla ELMA-ELMA karşılaştırılabilir dedup gerçeği. */
  ga4_paid_conversions: number;
  ga4_paid_revenue: number;
  /** platform_claimed_conversions / ga4_paid_conversions — ga4_paid_conversions>0 ise,
   *  yoksa null (karşılaştırma anlamsız). >1 = platformlar fazla iddia ediyor. */
  inflation_factor: number | null;
  /** Yalnız reklam harcaması (analitik kaynaklar harcama taşımaz). */
  ad_spend: number;
  /** ga4_paid_revenue / ad_spend — "Gerçek/Ücretli ROAS", de-duplike. GA4 yoksa/sıfırsa 0. */
  blended_roas: number;
  /** Media Efficiency Ratio: ga4_revenue (TOPLAM) / ad_spend — tüm-işletme geliri ÷
   *  reklam harcaması (organik dahil). Blended ROAS ile karıştırılmamalı. */
  mer: number;
  /** GA4 bağlantı/ölçüm kalitesi — bkz. AttributionDataQuality. */
  data_quality: AttributionDataQuality;
  channels: AttributionChannelRow[];
}

// --- API function ---

/** days: 1-90 (backend `Query(..., ge=1, le=90)`); varsayılan 30. */
export function getAttributionSummary(days = 30): Promise<AttributionSummary> {
  return authFetch<AttributionSummary>(
    `/api/v1/attribution/summary?days=${encodeURIComponent(String(days))}`,
  );
}
