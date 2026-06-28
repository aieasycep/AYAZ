import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { AuditReport, AuditGrade } from '@/lib/audit-api';
import { GRADE_LABELS } from '@/lib/audit-api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeReport(overrides: Partial<AuditReport> = {}): AuditReport {
  return {
    score: 78,
    grade: 'iyi',
    summary: 'Hesabınızda birkaç iyileştirme alanı tespit edildi.',
    counts: { pass: 12, warn: 3, fail: 1 },
    categories: [
      {
        key: 'ads',
        label: 'Reklam',
        checks: [
          {
            id: 'ads-budget-cap',
            severity: 'pass',
            title: 'Bütçe sınırı tanımlı',
            finding: 'Tüm kampanyalarda günlük bütçe sınırı mevcut.',
            recommendation: '',
          },
          {
            id: 'ads-ctr-low',
            severity: 'warn',
            title: 'Düşük tıklama oranı',
            finding: 'Bazı reklam gruplarında CTR ortalamanın altında.',
            recommendation: 'Reklam metinlerini ve görselleri güncelleyin.',
          },
        ],
      },
    ],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// GRADE_LABELS — constant contract
// ---------------------------------------------------------------------------

describe('GRADE_LABELS', () => {
  it('maps all four grades to Turkish labels', () => {
    expect(GRADE_LABELS.mukemmel).toBe('Mükemmel');
    expect(GRADE_LABELS.iyi).toBe('İyi');
    expect(GRADE_LABELS.orta).toBe('Orta');
    expect(GRADE_LABELS.zayif).toBe('Zayıf');
  });

  it('covers exactly the four valid grade keys', () => {
    const keys = Object.keys(GRADE_LABELS) as AuditGrade[];
    expect(keys).toHaveLength(4);
    expect(keys).toContain('mukemmel');
    expect(keys).toContain('iyi');
    expect(keys).toContain('orta');
    expect(keys).toContain('zayif');
  });
});

// ---------------------------------------------------------------------------
// runAudit — fetch mock
// ---------------------------------------------------------------------------

describe('runAudit', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', {
      getItem: (_key: string) => 'test-token',
      removeItem: vi.fn(),
      setItem: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('GETs /api/v1/audit/run with no query parameters', async () => {
    const mockReport = makeReport();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockReport),
      text: () => Promise.resolve(JSON.stringify(mockReport)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { runAudit } = await import('@/lib/audit-api');
    await runAudit();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/audit/run');
    expect(url).not.toContain('?');
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockReport = makeReport();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockReport),
      text: () => Promise.resolve(JSON.stringify(mockReport)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { runAudit } = await import('@/lib/audit-api');
    await runAudit();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('returns a parsed AuditReport with all fields', async () => {
    const mockReport = makeReport({ score: 62, grade: 'orta' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockReport),
      text: () => Promise.resolve(JSON.stringify(mockReport)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { runAudit } = await import('@/lib/audit-api');
    const result = await runAudit();

    expect(result.score).toBe(62);
    expect(result.grade).toBe('orta');
    expect(result.summary).toBe('Hesabınızda birkaç iyileştirme alanı tespit edildi.');
    expect(result.counts.pass).toBe(12);
    expect(result.counts.warn).toBe(3);
    expect(result.counts.fail).toBe(1);
    expect(result.categories).toHaveLength(1);
    expect(result.categories[0].key).toBe('ads');
    expect(result.categories[0].checks).toHaveLength(2);
  });

  it('throws with the server error message when response is not ok', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve('Servis geçici olarak kullanılamıyor'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { runAudit } = await import('@/lib/audit-api');
    await expect(runAudit()).rejects.toThrow('Servis geçici olarak kullanılamıyor');
  });

  it('throws "Oturum süresi doldu" on 401 response', async () => {
    // Prevent actual window.location redirect in test environment
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { runAudit } = await import('@/lib/audit-api');
    await expect(runAudit()).rejects.toThrow('Oturum süresi doldu');
  });

  it('parses check-level severity, finding, and recommendation correctly', async () => {
    const mockReport = makeReport();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockReport),
      text: () => Promise.resolve(JSON.stringify(mockReport)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { runAudit } = await import('@/lib/audit-api');
    const result = await runAudit();

    const passCheck = result.categories[0].checks[0];
    expect(passCheck.severity).toBe('pass');
    expect(passCheck.title).toBe('Bütçe sınırı tanımlı');

    const warnCheck = result.categories[0].checks[1];
    expect(warnCheck.severity).toBe('warn');
    expect(warnCheck.finding).toContain('CTR');
    expect(warnCheck.recommendation).toContain('metinleri');
  });

  it('handles a report with multiple categories and mixed severities', async () => {
    const mockReport = makeReport({
      score: 41,
      grade: 'zayif',
      counts: { pass: 5, warn: 4, fail: 7 },
      categories: [
        {
          key: 'tracking',
          label: 'Ölçümleme',
          checks: [
            {
              id: 'track-pixel',
              severity: 'fail',
              title: 'Piksel kurulu değil',
              finding: 'Meta pikseli tespit edilemedi.',
              recommendation: 'Events Manager üzerinden piksel ekleyin.',
            },
          ],
        },
        {
          key: 'budget',
          label: 'Bütçe',
          checks: [
            {
              id: 'budget-ok',
              severity: 'pass',
              title: 'Günlük bütçe tanımlı',
              finding: 'Tüm kampanyalarda bütçe mevcut.',
              recommendation: '',
            },
          ],
        },
      ],
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockReport),
      text: () => Promise.resolve(JSON.stringify(mockReport)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { runAudit } = await import('@/lib/audit-api');
    const result = await runAudit();

    expect(result.grade).toBe('zayif');
    expect(result.counts.fail).toBe(7);
    expect(result.categories).toHaveLength(2);
    expect(result.categories[0].key).toBe('tracking');
    expect(result.categories[0].checks[0].severity).toBe('fail');
    expect(result.categories[1].key).toBe('budget');
    expect(result.categories[1].checks[0].severity).toBe('pass');
  });
});
