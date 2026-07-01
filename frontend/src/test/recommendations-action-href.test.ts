import { describe, it, expect } from 'vitest';
import { buildRecActionHref } from '@/lib/recommendations-focus';

// ---------------------------------------------------------------------------
// Insight → action bridge: a recommendation whose action_href is /ads and
// whose rationale names a specific campaign (single-quoted, followed by
// "kampanyası") should route to /ads?focus=<campaign>. Everything else
// (non-/ads hrefs, or /ads recs with no safely-extractable campaign name —
// which today is ALL of them, since the feed has no structured campaign
// field) must pass through unchanged rather than fabricate a match.
// ---------------------------------------------------------------------------

describe('buildRecActionHref', () => {
  it('passes through non-/ads action_href unchanged', () => {
    const rec = { action_href: '/planning', rationale: 'Bütçe planı yok.' };
    expect(buildRecActionHref(rec)).toBe('/planning');
  });

  it('builds /ads?focus=<campaign> when rationale names a campaign', () => {
    const rec = {
      action_href: '/ads',
      rationale: "'Yaz İndirimi' kampanyası ROAS 1.0'ın altında.",
    };
    expect(buildRecActionHref(rec)).toBe('/ads?focus=Yaz%20%C4%B0ndirimi');
  });

  it('URL-encodes special characters in the campaign name', () => {
    const rec = {
      action_href: '/ads',
      rationale: "'Kış & Sonbahar' kampanyasında bütçe yoğunlaşması var.",
    };
    expect(buildRecActionHref(rec)).toBe(
      `/ads?focus=${encodeURIComponent('Kış & Sonbahar')}`,
    );
  });

  it('leaves action_href untouched when /ads rationale has no quoted campaign mention', () => {
    // This matches today's real audit-derived recs: account-wide findings
    // like "3 reklam ROAS<1.0" carry no campaign name at all.
    const rec = {
      action_href: '/ads',
      rationale: '3 reklam ROAS<1.0 (harcama dönüşüm değerinin üstünde).',
    };
    expect(buildRecActionHref(rec)).toBe('/ads');
  });

  it('does not fabricate a match from an ad-level quoted name (not a campaign)', () => {
    // Real shape of ads_budget_concentration: quotes an *ad* name, not a
    // campaign name, and never uses the word "kampanyası" — must not match.
    const rec = {
      action_href: '/ads',
      rationale: "'Yaz Reklamı #3' reklamı toplam harcamanın %62'sini alıyor.",
    };
    expect(buildRecActionHref(rec)).toBe('/ads');
  });

  it('ignores an empty quoted segment', () => {
    const rec = {
      action_href: '/ads',
      rationale: "'' kampanyası risk altında.",
    };
    expect(buildRecActionHref(rec)).toBe('/ads');
  });
});
