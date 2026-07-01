// Insight → action bridge helper for the recommendations feed.
//
// Kept in a standalone module (rather than inline in
// src/app/recommendations/page.tsx) because Next.js App Router page files
// may only export a small fixed set of named exports (default, metadata,
// etc.) — extra exports fail the build with
// "X is not a valid Page export field".
//
// When a recommendation's primary action points at /ads, we'd like to carry
// the specific campaign into the destination via ?focus=<name> so the user
// lands on the matching row instead of a generic, unfiltered list.
//
// As of today, the recommendations feed (src/lib/recommendations-api.ts) has
// NO structured campaign field on Recommendation — title/rationale are free
// text assembled by the backend (see backend/ayaz/services/recommendations.py).
// The only /ads-linked checks (ads_roas_below_1, ads_budget_concentration,
// ads_low_ctr) are account-wide or ad-level (quoting an *ad* name, not a
// *campaign* name) — there is no safe, non-fabricated way to derive a
// campaign name from them today.
//
// This helper stays a narrow, defensive extractor rather than a guess: it
// only rewrites the href when the rationale contains a single-quoted
// segment immediately followed by the Turkish word "kampanyası" (the
// pattern a campaign-scoped recommendation would use if the backend adds
// one later). Anything else — including the current ad-level/account-wide
// recs — passes through untouched, per instructions to not fabricate
// matches.

import type { Recommendation } from '@/lib/recommendations-api';

const CAMPAIGN_MENTION_RE = /'([^']+)'\s+kampanyas/i;

export function buildRecActionHref(
  rec: Pick<Recommendation, 'action_href' | 'rationale'>,
): string {
  if (rec.action_href !== '/ads') return rec.action_href;

  const match = rec.rationale.match(CAMPAIGN_MENTION_RE);
  if (!match) return rec.action_href;

  const campaignName = match[1].trim();
  if (!campaignName) return rec.action_href;

  return `/ads?focus=${encodeURIComponent(campaignName)}`;
}
