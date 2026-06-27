/**
 * Tests for the new insight feedback-loop client functions:
 *   applyInsight, reactInsight, and the new getInsights filter params.
 *
 * All tests mock globalThis.fetch and localStorage so they run in jsdom
 * without a real server.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { applyInsight, reactInsight, getInsights } from '@/lib/insights-api';
import type { Insight } from '@/lib/insights-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeInsight(overrides: Partial<Insight> = {}): Insight {
  return {
    id: 'ins-1',
    category: 'performance',
    severity: 'info',
    title: 'Test içgörüsü',
    body: 'Açıklama metni.',
    metric: 'cpc',
    channel: 'google_ads',
    entity_name: null,
    period_start: '2026-06-01',
    period_end: '2026-06-27',
    status: 'new',
    score: 75,
    created_at: '2026-06-27T00:00:00Z',
    applied_at: null,
    reaction: null,
    ...overrides,
  };
}

function mockFetch(body: unknown, ok = true, status = 200) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

beforeEach(() => {
  // Provide a token so authFetch does not redirect
  Object.defineProperty(globalThis, 'localStorage', {
    value: {
      getItem: vi.fn(() => 'test-token'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    },
    writable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// applyInsight
// ---------------------------------------------------------------------------

describe('applyInsight', () => {
  it('POSTs { applied: true } and returns the updated insight', async () => {
    const updated = makeInsight({ applied_at: '2026-06-27T12:00:00Z' });
    globalThis.fetch = mockFetch(updated);

    const result = await applyInsight('ins-1', true);

    expect(globalThis.fetch).toHaveBeenCalledOnce();
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/api/v1/insights/ins-1/apply');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ applied: true });
    expect(result.applied_at).toBe('2026-06-27T12:00:00Z');
  });

  it('POSTs { applied: false } to un-apply', async () => {
    const updated = makeInsight({ applied_at: null });
    globalThis.fetch = mockFetch(updated);

    const result = await applyInsight('ins-1', false);

    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ applied: false });
    expect(result.applied_at).toBeNull();
  });

  it('throws when the server returns a non-ok response', async () => {
    globalThis.fetch = mockFetch({ detail: 'Bulunamadı' }, false, 404);

    await expect(applyInsight('bad-id', true)).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// reactInsight
// ---------------------------------------------------------------------------

describe('reactInsight', () => {
  it('POSTs { reaction: "up" } and returns updated insight', async () => {
    const updated = makeInsight({ reaction: 'up' });
    globalThis.fetch = mockFetch(updated);

    const result = await reactInsight('ins-1', 'up');

    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/api/v1/insights/ins-1/react');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ reaction: 'up' });
    expect(result.reaction).toBe('up');
  });

  it('POSTs { reaction: "down" }', async () => {
    const updated = makeInsight({ reaction: 'down' });
    globalThis.fetch = mockFetch(updated);

    await reactInsight('ins-1', 'down');

    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ reaction: 'down' });
  });

  it('POSTs { reaction: null } to clear a reaction', async () => {
    const updated = makeInsight({ reaction: null });
    globalThis.fetch = mockFetch(updated);

    const result = await reactInsight('ins-1', null);

    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ reaction: null });
    expect(result.reaction).toBeNull();
  });

  it('throws when the server returns a non-ok response', async () => {
    globalThis.fetch = mockFetch('Server error', false, 500);

    await expect(reactInsight('ins-1', 'up')).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getInsights — new filter params
// ---------------------------------------------------------------------------

describe('getInsights — applied/reaction params', () => {
  it('appends applied=true to query string when applied filter is set', async () => {
    globalThis.fetch = mockFetch([makeInsight()]);

    await getInsights({ applied: true });

    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('applied=true');
  });

  it('does not append applied param when undefined', async () => {
    globalThis.fetch = mockFetch([makeInsight()]);

    await getInsights({ severity: 'info' });

    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).not.toContain('applied');
  });

  it('appends reaction param when provided', async () => {
    globalThis.fetch = mockFetch([makeInsight()]);

    await getInsights({ reaction: 'up' });

    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('reaction=up');
  });

  it('returns insights preserving applied_at and reaction fields', async () => {
    const raw = makeInsight({ applied_at: '2026-06-27T10:00:00Z', reaction: 'up' });
    globalThis.fetch = mockFetch([raw]);

    const results = await getInsights();

    expect(results[0].applied_at).toBe('2026-06-27T10:00:00Z');
    expect(results[0].reaction).toBe('up');
  });
});
