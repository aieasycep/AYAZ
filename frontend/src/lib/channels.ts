// Kanal anahtarı → kullanıcıya dönük Türkçe/moda etiket.
// Ham anahtarlar ("google_ads") arayüze SIZMAMALI — tablo/çip/etiketlerde
// daima channelLabel() kullanın.
const CHANNEL_LABELS: Record<string, string> = {
  google_ads: 'Google Ads',
  meta_ads: 'Meta Ads',
  tiktok_ads: 'TikTok Ads',
  linkedin_ads: 'LinkedIn Ads',
  microsoft_ads: 'Microsoft Ads',
  criteo: 'Criteo',
  pinterest_ads: 'Pinterest Ads',
  ga4: 'Google Analytics 4',
  search_console: 'Search Console',
  sample: 'Örnek Kaynak',
};

export function channelLabel(slug: string | null | undefined): string {
  if (!slug) return '';
  return CHANNEL_LABELS[slug.toLowerCase()] ?? slug;
}

// Artışın KÖTÜ olduğu (maliyet) metrikleri — delta rozet renkleri ekranlar
// arası tutarlı olsun diye tek yerden.
export const NEGATIVE_IS_GOOD = new Set(['spend', 'cpc', 'cpa', 'cpm']);

/** true = iyi (yeşil), false = kötü (kırmızı), null = nötr. */
export function deltaIsGood(metric: string, pct: number | null | undefined): boolean | null {
  if (pct === null || pct === undefined || pct === 0) return null;
  const up = pct > 0;
  return NEGATIVE_IS_GOOD.has(metric) ? !up : up;
}
