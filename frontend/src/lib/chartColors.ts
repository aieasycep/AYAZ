/**
 * Maps a channel slug to its --chart-* CSS variable token.
 * Usage: fill={channelColor('meta')}  →  fill="var(--chart-meta)"
 *
 * Unknown slugs cycle through --chart-4 / --chart-5 by hash.
 */
const CHANNEL_TOKENS: Record<string, string> = {
  meta: 'var(--chart-meta)',
  facebook: 'var(--chart-meta)',
  instagram: 'var(--chart-meta)',
  google: 'var(--chart-google)',
  google_ads: 'var(--chart-google)',
  tiktok: 'var(--chart-tiktok)',
  tiktok_ads: 'var(--chart-tiktok)',
};

const FALLBACK = ['var(--chart-4)', 'var(--chart-5)'];

export function channelColor(slug: string): string {
  const key = slug.toLowerCase().replace(/[^a-z0-9_]/g, '_');
  if (CHANNEL_TOKENS[key]) return CHANNEL_TOKENS[key];
  // deterministic fallback via simple hash
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return FALLBACK[h % FALLBACK.length];
}
