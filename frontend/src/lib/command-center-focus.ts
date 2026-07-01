// Insight → action bridge helper for Komuta Merkezi (Command Center)
// attention items.
//
// Kept in a standalone module (rather than inline in
// src/app/command-center/page.tsx) because Next.js App Router page files
// may only export a small fixed set of named exports (default, metadata,
// etc.) — extra exports fail the build with
// "X is not a valid Page export field".
//
// Attention items come straight from the backend (command_center.py) and
// link generically (e.g. "/ads"). As of today none of the backend-built
// attention items point at /ads at all (see _build_attention: insights,
// inbox, content, goals, budget only) — but if one is added later that both
// (a) links to /ads and (b) names a specific campaign in its title/detail,
// this appends ?focus=<campaign> so the destination can highlight it.
//
// We never invent a match: the campaign name must appear in a single-quoted
// segment in the title or detail (the convention used elsewhere in the
// backend's Turkish copy, e.g. audit findings quoting an ad/campaign name).
// Anything else — including every attention item shipped today — passes
// through with its original link, unchanged.

import type { AttentionItem } from '@/lib/command-center-api';

const CAMPAIGN_MENTION_RE = /'([^']+)'/;

export function buildAttentionHref(
  item: Pick<AttentionItem, 'link' | 'title' | 'detail'>,
): string {
  const [path, existingQuery] = item.link.split('?', 2);
  if (path !== '/ads') return item.link;

  const source = `${item.title} ${item.detail}`;
  const match = source.match(CAMPAIGN_MENTION_RE);
  if (!match) return item.link;

  const campaignName = match[1].trim();
  if (!campaignName) return item.link;

  const separator = existingQuery ? '&' : '?';
  return `${item.link}${separator}focus=${encodeURIComponent(campaignName)}`;
}
