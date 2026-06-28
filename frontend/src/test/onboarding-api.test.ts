import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { OnboardingStatus, OnboardingStep } from '@/lib/onboarding-api';

// ---------------------------------------------------------------------------
// Type contracts
// ---------------------------------------------------------------------------

describe('OnboardingStep type', () => {
  it('accepts a complete step object', () => {
    const step: OnboardingStep = {
      key: 'connect_ads',
      title: 'Reklam Hesabını Bağla',
      description: 'Meta Ads veya Google Ads hesabınızı bağlayın.',
      done: false,
      cta_label: 'Bağla',
      cta_link: '/connectors/meta',
    };
    expect(step.key).toBe('connect_ads');
    expect(step.done).toBe(false);
    expect(step.cta_label).toBe('Bağla');
  });

  it('accepts a completed step', () => {
    const step: OnboardingStep = {
      key: 'invite_team',
      title: 'Ekip Üyelerini Davet Et',
      description: 'Ekibinizi AYAZ\'a davet edin.',
      done: true,
      cta_label: 'Davet Et',
      cta_link: '/settings/team',
    };
    expect(step.done).toBe(true);
  });
});

describe('OnboardingStatus type', () => {
  it('accepts a full status payload with steps', () => {
    const status: OnboardingStatus = {
      total_steps: 5,
      completed_steps: 2,
      percent: 40,
      all_done: false,
      steps: [
        {
          key: 'connect_ads',
          title: 'Reklam Hesabını Bağla',
          description: 'Reklam hesabınızı bağlayın.',
          done: true,
          cta_label: 'Bağla',
          cta_link: '/connectors',
        },
        {
          key: 'invite_team',
          title: 'Ekibi Davet Et',
          description: 'Ekibinizi davet edin.',
          done: false,
          cta_label: 'Davet Et',
          cta_link: '/settings/team',
        },
      ],
    };
    expect(status.total_steps).toBe(5);
    expect(status.completed_steps).toBe(2);
    expect(status.percent).toBe(40);
    expect(status.all_done).toBe(false);
    expect(status.steps).toHaveLength(2);
  });

  it('accepts an all_done payload', () => {
    const status: OnboardingStatus = {
      total_steps: 3,
      completed_steps: 3,
      percent: 100,
      all_done: true,
      steps: [],
    };
    expect(status.all_done).toBe(true);
    expect(status.percent).toBe(100);
  });
});

// ---------------------------------------------------------------------------
// getOnboardingStatus — fetch mock
// ---------------------------------------------------------------------------

describe('getOnboardingStatus', () => {
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

  it('calls GET /api/v1/onboarding/status', async () => {
    const mockResponse: OnboardingStatus = {
      total_steps: 4,
      completed_steps: 1,
      percent: 25,
      all_done: false,
      steps: [
        {
          key: 'step_1',
          title: 'Adım 1',
          description: 'İlk adım.',
          done: true,
          cta_label: 'Git',
          cta_link: '/step-1',
        },
      ],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOnboardingStatus } = await import('@/lib/onboarding-api');
    const result = await getOnboardingStatus();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/onboarding/status');
    expect(result.total_steps).toBe(4);
    expect(result.completed_steps).toBe(1);
    expect(result.steps).toHaveLength(1);
  });

  it('sends the Bearer token from localStorage in the Authorization header', async () => {
    const mockResponse: OnboardingStatus = {
      total_steps: 2,
      completed_steps: 0,
      percent: 0,
      all_done: false,
      steps: [],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOnboardingStatus } = await import('@/lib/onboarding-api');
    await getOnboardingStatus();

    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = opts.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer test-token');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('returns the parsed OnboardingStatus with steps array intact', async () => {
    const mockResponse: OnboardingStatus = {
      total_steps: 3,
      completed_steps: 2,
      percent: 66,
      all_done: false,
      steps: [
        {
          key: 'connect_ads',
          title: 'Reklam Bağla',
          description: 'Reklam hesabınızı bağlayın.',
          done: true,
          cta_label: 'Bağla',
          cta_link: '/connectors',
        },
        {
          key: 'add_pixel',
          title: 'Piksel Ekle',
          description: 'Sitenize piksel ekleyin.',
          done: true,
          cta_label: 'Ekle',
          cta_link: '/tracking',
        },
        {
          key: 'invite_team',
          title: 'Ekibi Davet Et',
          description: 'Ekibinizi davet edin.',
          done: false,
          cta_label: 'Davet Et',
          cta_link: '/settings/team',
        },
      ],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOnboardingStatus } = await import('@/lib/onboarding-api');
    const result = await getOnboardingStatus();

    expect(result.steps).toHaveLength(3);
    expect(result.steps[0].done).toBe(true);
    expect(result.steps[2].done).toBe(false);
    expect(result.steps[2].key).toBe('invite_team');
    expect(result.percent).toBe(66);
  });

  it('throws when the server returns a non-ok status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Sunucu hatası'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOnboardingStatus } = await import('@/lib/onboarding-api');
    await expect(getOnboardingStatus()).rejects.toThrow('Sunucu hatası');
  });

  it('throws a Turkish session-expired error on 401', async () => {
    // Stub window.location to avoid jsdom navigation side-effects
    const mockLocation = { href: '' };
    Object.defineProperty(globalThis, 'window', {
      value: { location: mockLocation },
      writable: true,
      configurable: true,
    });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOnboardingStatus } = await import('@/lib/onboarding-api');
    await expect(getOnboardingStatus()).rejects.toThrow('Oturum süresi doldu');
  });

  it('returns all_done:true and percent:100 when every step is completed', async () => {
    const mockResponse: OnboardingStatus = {
      total_steps: 2,
      completed_steps: 2,
      percent: 100,
      all_done: true,
      steps: [
        {
          key: 's1',
          title: 'Adım 1',
          description: 'Açıklama.',
          done: true,
          cta_label: 'Git',
          cta_link: '/s1',
        },
        {
          key: 's2',
          title: 'Adım 2',
          description: 'Açıklama.',
          done: true,
          cta_label: 'Git',
          cta_link: '/s2',
        },
      ],
    };

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockResponse),
      text: () => Promise.resolve(JSON.stringify(mockResponse)),
    });
    vi.stubGlobal('fetch', fetchMock);

    const { getOnboardingStatus } = await import('@/lib/onboarding-api');
    const result = await getOnboardingStatus();

    expect(result.all_done).toBe(true);
    expect(result.percent).toBe(100);
    expect(result.steps.every((s) => s.done)).toBe(true);
  });
});
