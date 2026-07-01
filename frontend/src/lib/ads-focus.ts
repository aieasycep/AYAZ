// Insight → action bridge helpers for /ads.
//
// /ads honors a `?focus=<campaign name>` query param set by other screens
// (e.g. Öneriler, Komuta Merkezi) so a user clicking "bu kampanyaya git" from
// an insight lands on the matching row instead of a generic, unfiltered list.
//
// Kept in a standalone module (rather than inline in src/app/ads/page.tsx)
// because Next.js App Router page files may only export a small fixed set
// of named exports (default, metadata, etc.) — extra exports fail the build
// with "X is not a valid Page export field".

import type { Campaign } from '@/lib/ads-api';

// Turkish-locale-correct lowercasing — plain .toLowerCase() turns 'İ' into
// 'i̇' (dotted i + combining dot above) instead of 'i', which breaks
// case-insensitive matching against Turkish campaign names like
// "Kış İndirim Kampanyası". Used by both applyFocus and filterCampaignsByName.
function trLower(s: string): string {
  return s.toLocaleLowerCase('tr');
}

// applyFocus is a pure helper (no DOM/router access) so it's easy to unit
// test: given the fetched campaigns and a focus string, it returns the list
// reordered with the best case-insensitive substring match first, plus the
// matched campaign's id (or null if nothing matched / no focus given).
// Callers combine matchedId with rowFocused styling + scrollIntoView.
export interface FocusResult {
  campaigns: Campaign[];
  matchedId: string | null;
}

export function applyFocus(campaigns: Campaign[], focus: string | null): FocusResult {
  const trimmed = focus?.trim();
  if (!trimmed) {
    return { campaigns, matchedId: null };
  }
  const needle = trLower(trimmed);

  // Prefer an exact (case-insensitive) name match; fall back to the first
  // campaign whose name contains the focus string.
  const exact = campaigns.find((c) => trLower(c.campaign_name) === needle);
  const match =
    exact ?? campaigns.find((c) => trLower(c.campaign_name).includes(needle));

  if (!match) {
    return { campaigns, matchedId: null };
  }

  const rest = campaigns.filter((c) => c.campaign_id !== match.campaign_id);
  return { campaigns: [match, ...rest], matchedId: match.campaign_id };
}

// Pure helper backing the "Kampanya ara" input: case-insensitive substring
// match against campaign_name. Empty/whitespace query returns the list
// unchanged.
export function filterCampaignsByName(campaigns: Campaign[], query: string): Campaign[] {
  const trimmed = trLower(query.trim());
  if (!trimmed) return campaigns;
  return campaigns.filter((c) => trLower(c.campaign_name).includes(trimmed));
}
