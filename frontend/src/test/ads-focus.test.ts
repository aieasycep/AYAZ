import { describe, it, expect } from 'vitest';
import { applyFocus, filterCampaignsByName } from '@/lib/ads-focus';
import type { Campaign } from '@/lib/ads-api';

// ---------------------------------------------------------------------------
// Insight → action bridge: /ads honors ?focus=<campaign name> by reordering
// the campaign list (matched row first) and reporting the matched id so the
// page can highlight + scroll to it. These tests cover the pure helper only
// — no DOM/router involved.
// ---------------------------------------------------------------------------

function makeCampaign(overrides: Partial<Campaign> = {}): Campaign {
  return {
    campaign_id: 'c1',
    campaign_name: 'Yaz Kampanyası',
    channel: 'meta',
    status: 'active',
    spend: 1000,
    impressions: 10000,
    clicks: 500,
    conversions: 20,
    conversion_value: 4000,
    ctr: 0.05,
    cpc: 2,
    cpa: 50,
    roas: 4,
    ...overrides,
  };
}

describe('applyFocus', () => {
  it('returns the list unchanged and matchedId null when focus is null', () => {
    const campaigns = [
      makeCampaign({ campaign_id: 'c1', campaign_name: 'Yaz Kampanyası' }),
      makeCampaign({ campaign_id: 'c2', campaign_name: 'Kış Kampanyası' }),
    ];
    const result = applyFocus(campaigns, null);
    expect(result.campaigns).toEqual(campaigns);
    expect(result.matchedId).toBeNull();
  });

  it('returns the list unchanged and matchedId null when focus is empty/whitespace', () => {
    const campaigns = [makeCampaign({ campaign_id: 'c1' })];
    expect(applyFocus(campaigns, '').matchedId).toBeNull();
    expect(applyFocus(campaigns, '   ').matchedId).toBeNull();
  });

  it('brings the matching campaign to the front (case-insensitive substring match)', () => {
    const campaigns = [
      makeCampaign({ campaign_id: 'c1', campaign_name: 'Yaz Kampanyası' }),
      makeCampaign({ campaign_id: 'c2', campaign_name: 'Kış İndirim Kampanyası' }),
      makeCampaign({ campaign_id: 'c3', campaign_name: 'Bahar Lansmanı' }),
    ];
    const result = applyFocus(campaigns, 'kış indirim');
    expect(result.matchedId).toBe('c2');
    expect(result.campaigns.map((c) => c.campaign_id)).toEqual(['c2', 'c1', 'c3']);
  });

  it('prefers an exact case-insensitive match over a substring match', () => {
    const campaigns = [
      makeCampaign({ campaign_id: 'c1', campaign_name: 'Kış Kampanyası Ek' }),
      makeCampaign({ campaign_id: 'c2', campaign_name: 'kış kampanyası' }),
    ];
    const result = applyFocus(campaigns, 'Kış Kampanyası');
    expect(result.matchedId).toBe('c2');
    expect(result.campaigns[0].campaign_id).toBe('c2');
  });

  it('leaves order and matchedId untouched when nothing matches', () => {
    const campaigns = [
      makeCampaign({ campaign_id: 'c1', campaign_name: 'Yaz Kampanyası' }),
      makeCampaign({ campaign_id: 'c2', campaign_name: 'Kış Kampanyası' }),
    ];
    const result = applyFocus(campaigns, 'Sonbahar');
    expect(result.matchedId).toBeNull();
    expect(result.campaigns).toEqual(campaigns);
  });

  it('does not mutate the input array', () => {
    const campaigns = [
      makeCampaign({ campaign_id: 'c1', campaign_name: 'Yaz Kampanyası' }),
      makeCampaign({ campaign_id: 'c2', campaign_name: 'Kış Kampanyası' }),
    ];
    const original = [...campaigns];
    applyFocus(campaigns, 'kış');
    expect(campaigns).toEqual(original);
  });
});

describe('filterCampaignsByName', () => {
  it('returns the full list when query is empty/whitespace', () => {
    const campaigns = [
      makeCampaign({ campaign_id: 'c1', campaign_name: 'Yaz Kampanyası' }),
      makeCampaign({ campaign_id: 'c2', campaign_name: 'Kış Kampanyası' }),
    ];
    expect(filterCampaignsByName(campaigns, '')).toEqual(campaigns);
    expect(filterCampaignsByName(campaigns, '   ')).toEqual(campaigns);
  });

  it('filters case-insensitively by substring', () => {
    const campaigns = [
      makeCampaign({ campaign_id: 'c1', campaign_name: 'Yaz Kampanyası' }),
      makeCampaign({ campaign_id: 'c2', campaign_name: 'Kış Kampanyası' }),
    ];
    const result = filterCampaignsByName(campaigns, 'YAZ');
    expect(result).toHaveLength(1);
    expect(result[0].campaign_id).toBe('c1');
  });

  it('returns an empty array when nothing matches', () => {
    const campaigns = [makeCampaign({ campaign_name: 'Yaz Kampanyası' })];
    expect(filterCampaignsByName(campaigns, 'sonbahar')).toEqual([]);
  });
});
