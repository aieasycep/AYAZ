import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ScoresResponse, ScoreRating } from '@/lib/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a minimal ScoresResponse fixture. */
function makeScoresResponse(overrides: Partial<ScoresResponse> = {}): ScoresResponse {
  return {
    date_from: '2026-05-01',
    date_to: '2026-05-31',
    overall: {
      score: 72,
      label: 'Genel Etkinlik',
      rating: 'iyi',
    },
    components: [
      {
        key: 'efficiency',
        label: 'Verimlilik',
        score: 78,
        value: 5.0,
        baseline: 4.0,
        basis: 'ROAS 5.00x · önceki dönem 4.00x (+%25)',
      },
      {
        key: 'engagement',
        label: 'Etkileşim',
        score: 55,
        value: 0.032,
        baseline: 0.028,
        basis: 'CTR %3.20 · önceki dönem %2.80 (+%14)',
      },
      {
        key: 'conversion',
        label: 'Dönüşüm',
        score: 40,
        value: 120,
        baseline: 140,
        basis: 'Dönüşüm 120 · önceki dönem 140 (-%14)',
      },
    ],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// ScoresResponse type contract
// ---------------------------------------------------------------------------

describe('ScoresResponse type contract', () => {
  it('overall carries score, label, and rating', () => {
    const resp = makeScoresResponse();
    expect(resp.overall.score).toBe(72);
    expect(resp.overall.label).toBe('Genel Etkinlik');
    expect(resp.overall.rating).toBe('iyi');
  });

  it('components array has three entries with required fields', () => {
    const resp = makeScoresResponse();
    expect(resp.components).toHaveLength(3);
    const eff = resp.components[0];
    expect(eff.key).toBe('efficiency');
    expect(eff.score).toBe(78);
    expect(eff.value).toBe(5.0);
    expect(eff.baseline).toBe(4.0);
    expect(typeof eff.basis).toBe('string');
  });

  it('rating values are one of the three allowed strings', () => {
    const valid: ScoreRating[] = ['iyi', 'orta', 'zayıf'];
    const resp = makeScoresResponse();
    expect(valid).toContain(resp.overall.rating);
  });

  it('accepts rating "orta"', () => {
    const resp = makeScoresResponse({ overall: { score: 50, label: 'Genel Etkinlik', rating: 'orta' } });
    expect(resp.overall.rating).toBe('orta');
  });

  it('accepts rating "zayıf"', () => {
    const resp = makeScoresResponse({ overall: { score: 20, label: 'Genel Etkinlik', rating: 'zayıf' } });
    expect(resp.overall.rating).toBe('zayıf');
  });
});

// ---------------------------------------------------------------------------
// getScores — fetch integration (mock)
// ---------------------------------------------------------------------------

describe('getScores', () => {
  beforeEach(() => {
    // Provide a localStorage stub so authFetch can read the token
    Object.defineProperty(globalThis, 'localStorage', {
      value: {
        getItem: () => 'test-token',
        removeItem: vi.fn(),
        setItem: vi.fn(),
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it('calls GET /api/v1/dashboard/scores with date_from and date_to query params', async () => {
    const mockPayload = makeScoresResponse();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockPayload),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getScores } = await import('@/lib/api');
    const result = await getScores('2026-05-01', '2026-05-31');

    expect(fetchMock).toHaveBeenCalledOnce();
    const [calledUrl] = fetchMock.mock.calls[0] as [string];
    expect(calledUrl).toContain('/api/v1/dashboard/scores');
    expect(calledUrl).toContain('date_from=2026-05-01');
    expect(calledUrl).toContain('date_to=2026-05-31');

    expect(result.overall.score).toBe(72);
    expect(result.overall.rating).toBe('iyi');
    expect(result.components).toHaveLength(3);
  });

  it('includes Authorization header with the stored token', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(makeScoresResponse()),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getScores } = await import('@/lib/api');
    await getScores('2026-05-01', '2026-05-31');

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = options.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: () => Promise.resolve('date_from cannot be after date_to'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getScores } = await import('@/lib/api');
    await expect(getScores('2026-06-01', '2026-05-01')).rejects.toThrow(
      'date_from cannot be after date_to',
    );
  });

  it('returns correct component keys for all three dimensions', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(makeScoresResponse()),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getScores } = await import('@/lib/api');
    const result = await getScores('2026-05-01', '2026-05-31');

    const keys = result.components.map((c) => c.key);
    expect(keys).toContain('efficiency');
    expect(keys).toContain('engagement');
    expect(keys).toContain('conversion');
  });
});

// ---------------------------------------------------------------------------
// scoreToRating threshold logic (pure, mirrored here for isolation)
// ---------------------------------------------------------------------------

/** Mirror of the internal scoreToRating from PerformanceScore.tsx */
function scoreToRating(score: number): ScoreRating {
  if (score >= 67) return 'iyi';
  if (score >= 34) return 'orta';
  return 'zayıf';
}

describe('scoreToRating thresholds', () => {
  it('score 100 → iyi', () => expect(scoreToRating(100)).toBe('iyi'));
  it('score 67 → iyi (boundary)', () => expect(scoreToRating(67)).toBe('iyi'));
  it('score 66 → orta (below iyi boundary)', () => expect(scoreToRating(66)).toBe('orta'));
  it('score 50 → orta', () => expect(scoreToRating(50)).toBe('orta'));
  it('score 34 → orta (boundary)', () => expect(scoreToRating(34)).toBe('orta'));
  it('score 33 → zayıf (below orta boundary)', () => expect(scoreToRating(33)).toBe('zayıf'));
  it('score 0 → zayıf', () => expect(scoreToRating(0)).toBe('zayıf'));
});
