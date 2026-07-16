import { describe, it, expect } from 'vitest';
import { normaliseGoal, goalPayloadToBackend } from '@/lib/goals-api';
import type { Goal } from '@/lib/goals-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeGoal(overrides: Partial<Goal & { channel_filter?: string | null }> = {}): Goal & { channel_filter?: string | null } {
  return {
    id: 'g1',
    name: 'Test Hedefi',
    metric: 'roas',
    target_value: 4.0,
    period: 'ay',
    period_start: '2026-01-01',
    period_end: '2026-01-31',
    channel: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// normaliseGoal — channel_filter → channel mapping
// ---------------------------------------------------------------------------

describe('normaliseGoal', () => {
  it('maps channel_filter to channel when channel is null', () => {
    const goal = makeGoal({ channel: null, channel_filter: 'google_ads' });
    const result = normaliseGoal(goal);
    expect(result.channel).toBe('google_ads');
  });

  it('does not overwrite channel when it is already set', () => {
    const goal = makeGoal({ channel: 'meta_ads', channel_filter: 'google_ads' });
    const result = normaliseGoal(goal);
    // channel is already set → channel_filter must not replace it
    expect(result.channel).toBe('meta_ads');
  });

  it('leaves channel as null when both channel and channel_filter are absent', () => {
    const goal = makeGoal({ channel: null });
    const result = normaliseGoal(goal);
    expect(result.channel).toBeNull();
  });

  it('handles channel_filter: null gracefully (channel stays null)', () => {
    const goal = makeGoal({ channel: null, channel_filter: null });
    const result = normaliseGoal(goal);
    expect(result.channel).toBeNull();
  });

  it('preserves all other goal fields unchanged', () => {
    const goal = makeGoal({ channel: null, channel_filter: 'tiktok_ads' });
    const result = normaliseGoal(goal);
    expect(result.id).toBe('g1');
    expect(result.metric).toBe('roas');
    expect(result.target_value).toBe(4.0);
  });
});

// ---------------------------------------------------------------------------
// goalPayloadToBackend — channel → channel_filter mapping
// ---------------------------------------------------------------------------

describe('goalPayloadToBackend', () => {
  it('renames channel to channel_filter in the output', () => {
    const payload = { name: 'ROAS Goal', metric: 'roas' as const, channel: 'google_ads' };
    const result = goalPayloadToBackend(payload);
    expect((result as Record<string, unknown>).channel_filter).toBe('google_ads');
    expect('channel' in result).toBe(false);
  });

  it('sets channel_filter: null when channel is null', () => {
    const payload = { name: 'Goal', channel: null };
    const result = goalPayloadToBackend(payload);
    expect((result as Record<string, unknown>).channel_filter).toBeNull();
    expect('channel' in result).toBe(false);
  });

  it('does not add channel_filter when channel is not present in payload', () => {
    // Açık tip: goalPayloadToBackend generic kısıtı { channel?: ... } — sadece
    // { name } literal'i "weak type" (TS2559) verir; opsiyonel channel'ı tipte belirtiyoruz.
    const payload: { name: string; channel?: string | null } = { name: 'Goal without channel' };
    const result = goalPayloadToBackend(payload);
    expect('channel_filter' in result).toBe(false);
    expect('channel' in result).toBe(false);
    expect((result as Record<string, unknown>).name).toBe('Goal without channel');
  });

  it('preserves all other payload fields', () => {
    const payload = {
      name: 'Spend Goal',
      metric: 'spend' as const,
      target_value: 10000,
      channel: 'meta_ads',
    };
    const result = goalPayloadToBackend(payload);
    expect((result as Record<string, unknown>).name).toBe('Spend Goal');
    expect((result as Record<string, unknown>).target_value).toBe(10000);
    expect((result as Record<string, unknown>).channel_filter).toBe('meta_ads');
  });

  it('round-trips: normaliseGoal(backend) recovers original channel', () => {
    const original = makeGoal({ channel: 'google_ads' });
    // Simulate what the backend does: it stores channel_filter
    const backend = goalPayloadToBackend({ channel: original.channel });
    // Backend response has channel_filter but no channel
    const backendGoal = { ...original, channel: null, ...backend } as Goal & { channel_filter?: string | null };
    const recovered = normaliseGoal(backendGoal);
    expect(recovered.channel).toBe('google_ads');
  });
});
