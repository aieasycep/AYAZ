import { describe, it, expect } from 'vitest';
import { normaliseBriefing } from '@/lib/briefing-api';
import type { Briefing } from '@/lib/briefing-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMinimalBriefing(overrides: Partial<Briefing> = {}): Briefing {
  return {
    id: 'b1',
    briefing_date: '2026-01-15',
    headline: 'Test briefing',
    body: {
      performance_delta: {},
      top_insights: [],
      top_recommendation: { message: 'OK', suggested_action: 'Do it' },
      goals_status: [],
    },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// normaliseBriefing — performance_delta transformation
// ---------------------------------------------------------------------------

describe('normaliseBriefing — performance_delta', () => {
  it('transforms backend {yesterday/prior_day/delta} shape into per-metric map', () => {
    const briefing = makeMinimalBriefing({
      body: {
        performance_delta: {
          yesterday: { spend: 1000, roas: 3.5, conversions: 50 },
          prior_day: { spend: 800, roas: 3.0, conversions: 40 },
          delta: { spend_pct: 0.25, roas_pct: 0.167, conversions_pct: 0.25 },
        } as never,
        top_insights: [],
        top_recommendation: { message: 'OK', suggested_action: 'Do it' },
        goals_status: [],
      },
    });

    const result = normaliseBriefing(briefing);
    const pd = result.body.performance_delta as Record<
      string,
      { value: number; prev: number; pct: number }
    >;

    expect(pd.spend).toEqual({ value: 1000, prev: 800, pct: 25 });
    expect(pd.roas.value).toBe(3.5);
    expect(pd.roas.prev).toBe(3.0);
    // delta fraction * 100
    expect(pd.roas.pct).toBeCloseTo(16.7, 1);
    expect(pd.conversions).toEqual({ value: 50, prev: 40, pct: 25 });
  });

  it('leaves already-normalised shape untouched (no yesterday/prior_day/delta keys)', () => {
    const alreadyNorm = {
      spend: { value: 500, prev: 400, pct: 25 },
      roas: { value: 4, prev: 3.5, pct: 14.3 },
    };
    const briefing = makeMinimalBriefing({
      body: {
        performance_delta: alreadyNorm as never,
        top_insights: [],
        top_recommendation: { message: 'OK', suggested_action: 'Do it' },
        goals_status: [],
      },
    });

    const result = normaliseBriefing(briefing);
    const pd = result.body.performance_delta as typeof alreadyNorm;
    expect(pd.spend).toEqual({ value: 500, prev: 400, pct: 25 });
    expect(pd.roas).toEqual({ value: 4, prev: 3.5, pct: 14.3 });
  });

  it('handles missing metrics in backend shape (missing value → 0)', () => {
    const briefing = makeMinimalBriefing({
      body: {
        performance_delta: {
          yesterday: { spend: 200 },
          prior_day: {},
          delta: { spend_pct: 0.1 },
        } as never,
        top_insights: [],
        top_recommendation: { message: 'OK', suggested_action: 'Do it' },
        goals_status: [],
      },
    });

    const result = normaliseBriefing(briefing);
    const pd = result.body.performance_delta as Record<
      string,
      { value: number; prev: number; pct: number }
    >;
    expect(pd.spend).toEqual({ value: 200, prev: 0, pct: 10 });
    // roas and conversions not present in yesterday → omitted
    expect(pd.roas).toBeUndefined();
    expect(pd.conversions).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// normaliseBriefing — goals_status transformation
// ---------------------------------------------------------------------------

describe('normaliseBriefing — goals_status', () => {
  it('maps backend goal items: uses recommendation as forecast when no forecast field', () => {
    const briefing = makeMinimalBriefing({
      body: {
        performance_delta: {},
        top_insights: [],
        top_recommendation: { message: 'OK', suggested_action: 'Do it' },
        goals_status: [
          {
            goal_id: 'g1',
            name: 'ROAS Hedefi',
            metric: 'roas',
            status: 'on_track',
            recommendation: 'İyi gidiyor',
            forecast_value: 4.2,
          } as never,
        ],
      },
    });

    const result = normaliseBriefing(briefing);
    const first = result.body.goals_status[0];
    expect(first.name).toBe('ROAS Hedefi');
    expect(first.status).toBe('on_track');
    // recommendation is preferred over forecast_value
    expect(first.forecast).toBe('İyi gidiyor');
  });

  it('falls back to forecast_value string when recommendation absent', () => {
    const briefing = makeMinimalBriefing({
      body: {
        performance_delta: {},
        top_insights: [],
        top_recommendation: { message: 'OK', suggested_action: 'Do it' },
        goals_status: [
          {
            name: 'Spend Hedefi',
            status: 'at_risk',
            forecast_value: 7500,
          } as never,
        ],
      },
    });

    const result = normaliseBriefing(briefing);
    expect(result.body.goals_status[0].forecast).toBe('7500');
  });

  it('returns empty array when goals_status is null/undefined', () => {
    const briefing = makeMinimalBriefing({
      body: {
        performance_delta: {},
        top_insights: [],
        top_recommendation: { message: 'OK', suggested_action: 'Do it' },
        goals_status: null as never,
      },
    });

    const result = normaliseBriefing(briefing);
    expect(result.body.goals_status).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// normaliseBriefing — top_insights guard
// ---------------------------------------------------------------------------

describe('normaliseBriefing — top_insights guard', () => {
  it('replaces null top_insights with empty array', () => {
    const briefing = makeMinimalBriefing({
      body: {
        performance_delta: {},
        top_insights: null as never,
        top_recommendation: { message: 'OK', suggested_action: 'Do it' },
        goals_status: [],
      },
    });

    const result = normaliseBriefing(briefing);
    expect(Array.isArray(result.body.top_insights)).toBe(true);
    expect(result.body.top_insights).toHaveLength(0);
  });

  it('preserves existing top_insights array', () => {
    const briefing = makeMinimalBriefing({
      body: {
        performance_delta: {},
        top_insights: [
          { severity: 'critical', title: 'Dikkat!' },
          { severity: 'info', title: 'Bilgi' },
        ],
        top_recommendation: { message: 'OK', suggested_action: 'Do it' },
        goals_status: [],
      },
    });

    const result = normaliseBriefing(briefing);
    expect(result.body.top_insights).toHaveLength(2);
    expect(result.body.top_insights[0].severity).toBe('critical');
  });
});
