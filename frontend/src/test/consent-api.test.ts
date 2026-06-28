import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type {
  ConsentCenter,
  ConsentSignal,
  ConsentDestination,
  ConsentSource,
  ConsentCompliance,
  ConsentCheck,
  ConsentAuditEntry,
  ConsentGrade,
  ConsentCheckStatus,
} from '@/lib/consent-api';
import { GRADE_LABELS } from '@/lib/consent-api';

// ---------------------------------------------------------------------------
// GRADE_LABELS constant
// ---------------------------------------------------------------------------

describe('GRADE_LABELS', () => {
  it('maps all three grades to correct Turkish labels', () => {
    expect(GRADE_LABELS.uyumlu).toBe('Uyumlu');
    expect(GRADE_LABELS.kismi).toBe('Kısmi uyum');
    expect(GRADE_LABELS.eksik).toBe('Eksik');
  });

  it('covers exactly the three ConsentGrade values', () => {
    const keys = Object.keys(GRADE_LABELS) as ConsentGrade[];
    expect(keys).toHaveLength(3);
    expect(keys).toContain('uyumlu');
    expect(keys).toContain('kismi');
    expect(keys).toContain('eksik');
  });
});

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('ConsentSignal type', () => {
  it('accepts a full signal payload', () => {
    const signal: ConsentSignal = {
      key: 'ad_storage',
      label: 'Reklam Depolama',
      granted: 80,
      denied: 20,
      grant_rate_pct: 80.0,
      description: 'Reklam amaçlı depolama rızası.',
    };
    expect(signal.key).toBe('ad_storage');
    expect(signal.grant_rate_pct).toBe(80.0);
  });
});

describe('ConsentDestination type', () => {
  it('accepts a full destination payload', () => {
    const dest: ConsentDestination = {
      name: 'meta_capi',
      platform: 'meta',
      consent_required: true,
      required_consent: ['ad_user_data'],
      forwarded: 60,
      skipped_no_consent: 20,
      posture_label: 'Katı (rıza zorunlu)',
    };
    expect(dest.name).toBe('meta_capi');
    expect(dest.required_consent).toContain('ad_user_data');
  });
});

describe('ConsentSource type', () => {
  it('accepts a full source payload', () => {
    const src: ConsentSource = {
      name: 'Demo Web Sitesi',
      consent_cookie_var: 'ayaz_consent',
      configured: true,
      events: 100,
    };
    expect(src.name).toBe('Demo Web Sitesi');
    expect(src.configured).toBe(true);
  });
});

describe('ConsentCheck type', () => {
  it('accepts a full check payload', () => {
    const check: ConsentCheck = {
      id: 'acik_riza_mekanizmasi',
      label: 'Açık rıza mekanizması',
      status: 'pass' as ConsentCheckStatus,
      finding: 'Rıza mekanizması mevcut.',
      recommendation: '',
    };
    expect(check.id).toBe('acik_riza_mekanizmasi');
    expect(check.status).toBe('pass');
  });
});

describe('ConsentAuditEntry type', () => {
  it('accepts a full audit entry payload', () => {
    const entry: ConsentAuditEntry = {
      event_time: '2026-06-28T10:00:00Z',
      event_name: 'Purchase',
      consent: true,
      status: 'forwarded',
      status_label: 'İletildi',
      signals_summary: '4/4 onaylı',
    };
    expect(entry.event_name).toBe('Purchase');
    expect(entry.consent).toBe(true);
    expect(entry.status_label).toBe('İletildi');
  });
});

// ---------------------------------------------------------------------------
// Full ConsentCenter shape
// ---------------------------------------------------------------------------

function makeMockConsentCenter(): ConsentCenter {
  return {
    generated_at: '2026-06-28T12:00:00Z',
    period: { date_from: '2026-05-29', date_to: '2026-06-28' },
    summary: {
      total_events: 100,
      consented_events: 80,
      consent_rate_pct: 80.0,
      skipped_no_consent: 20,
      granular_supported: true,
    },
    signals: [
      {
        key: 'ad_storage',
        label: 'Reklam Depolama',
        granted: 80,
        denied: 20,
        grant_rate_pct: 80.0,
        description: 'Reklam depolama açıklaması.',
      },
      {
        key: 'analytics_storage',
        label: 'Analitik Depolama',
        granted: 80,
        denied: 20,
        grant_rate_pct: 80.0,
        description: 'Analitik depolama açıklaması.',
      },
      {
        key: 'ad_user_data',
        label: 'Reklam Kullanıcı Verisi',
        granted: 80,
        denied: 20,
        grant_rate_pct: 80.0,
        description: 'Reklam kullanıcı verisi açıklaması.',
      },
      {
        key: 'ad_personalization',
        label: 'Reklam Kişiselleştirme',
        granted: 56,
        denied: 44,
        grant_rate_pct: 56.0,
        description: 'Reklam kişiselleştirme açıklaması.',
      },
    ],
    destinations: [
      {
        name: 'meta_capi',
        platform: 'meta',
        consent_required: true,
        required_consent: ['ad_user_data'],
        forwarded: 60,
        skipped_no_consent: 20,
        posture_label: 'Katı (rıza zorunlu)',
      },
      {
        name: 'ga4_mp',
        platform: 'ga4',
        consent_required: false,
        required_consent: [],
        forwarded: 80,
        skipped_no_consent: 0,
        posture_label: 'Gevşek (rıza opsiyonel)',
      },
    ],
    sources: [
      {
        name: 'Demo Web Sitesi',
        consent_cookie_var: 'ayaz_consent',
        configured: true,
        events: 100,
      },
    ],
    compliance: {
      score: 86,
      grade: 'uyumlu',
      counts: { pass: 6, warn: 1, fail: 0 },
      checks: [
        {
          id: 'acik_riza_mekanizmasi',
          label: 'Açık rıza mekanizması',
          status: 'pass',
          finding: 'Rıza mekanizması mevcut.',
          recommendation: '',
        },
      ],
    },
    audit_trail: [
      {
        event_time: '2026-06-28T10:00:00Z',
        event_name: 'Purchase',
        consent: true,
        status: 'forwarded',
        status_label: 'İletildi',
        signals_summary: '4/4 onaylı',
      },
    ],
  };
}

// ---------------------------------------------------------------------------
// getConsentCenter — fetch mock
// ---------------------------------------------------------------------------

describe('getConsentCenter', () => {
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

  it('GETs /consent/center with no query string when no dates given', async () => {
    const mockResponse = makeMockConsentCenter();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getConsentCenter } = await import('@/lib/consent-api');
    const result = await getConsentCenter();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/consent/center');
    expect(url).not.toContain('?');
    expect(result.summary.total_events).toBe(100);
  });

  it('appends date_from and date_to as query parameters when given', async () => {
    const mockResponse = makeMockConsentCenter();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getConsentCenter } = await import('@/lib/consent-api');
    await getConsentCenter('2026-06-01', '2026-06-28');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).toContain('date_to=2026-06-28');
  });

  it('appends only date_from when date_to is omitted', async () => {
    const mockResponse = makeMockConsentCenter();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getConsentCenter } = await import('@/lib/consent-api');
    await getConsentCenter('2026-06-01');

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('date_from=2026-06-01');
    expect(url).not.toContain('date_to=');
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse = makeMockConsentCenter();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getConsentCenter } = await import('@/lib/consent-api');
    await getConsentCenter();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('parses full shape including signals, destinations, compliance.checks, and audit_trail', async () => {
    const mockResponse = makeMockConsentCenter();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getConsentCenter } = await import('@/lib/consent-api');
    const result = await getConsentCenter();

    // signals
    expect(result.signals).toHaveLength(4);
    expect(result.signals[0].key).toBe('ad_storage');
    expect(result.signals[3].key).toBe('ad_personalization');
    expect(result.signals[3].grant_rate_pct).toBe(56.0);

    // destinations
    expect(result.destinations).toHaveLength(2);
    expect(result.destinations[0].name).toBe('meta_capi');
    expect(result.destinations[0].required_consent).toContain('ad_user_data');
    expect(result.destinations[1].skipped_no_consent).toBe(0);

    // compliance.checks
    expect(result.compliance.score).toBe(86);
    expect(result.compliance.grade).toBe('uyumlu');
    expect(result.compliance.counts.pass).toBe(6);
    expect(result.compliance.counts.warn).toBe(1);
    expect(result.compliance.counts.fail).toBe(0);
    expect(result.compliance.checks).toHaveLength(1);
    expect(result.compliance.checks[0].id).toBe('acik_riza_mekanizmasi');
    expect(result.compliance.checks[0].status).toBe('pass');

    // audit_trail
    expect(result.audit_trail).toHaveLength(1);
    expect(result.audit_trail[0].event_name).toBe('Purchase');
    expect(result.audit_trail[0].status_label).toBe('İletildi');
    expect(result.audit_trail[0].signals_summary).toBe('4/4 onaylı');
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getConsentCenter } = await import('@/lib/consent-api');
    await expect(getConsentCenter()).rejects.toThrow('Sunucu hatası');
  });

  it('throws with "Oturum süresi doldu" on 401', async () => {
    Object.defineProperty(globalThis, 'window', {
      value: {
        localStorage: {
          getItem: () => 'test-token',
          removeItem: vi.fn(),
          setItem: vi.fn(),
        },
        location: { href: '' },
      },
      writable: true,
      configurable: true,
    });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getConsentCenter } = await import('@/lib/consent-api');
    await expect(getConsentCenter()).rejects.toThrow('Oturum süresi doldu');
  });
});
