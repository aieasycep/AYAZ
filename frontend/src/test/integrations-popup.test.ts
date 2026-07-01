import { describe, it, expect, vi, afterEach } from 'vitest';
import type { ConnectResponse } from '@/lib/integrations-api';

// ---------------------------------------------------------------------------
// Pure helper functions that mirror what the integrations page will implement.
// Defined here so they can be tested in isolation without rendering React.
// ---------------------------------------------------------------------------

function buildPopupFeatures(width = 600, height = 720): string {
  const left = Math.round(window.screenX + (window.outerWidth - width) / 2);
  const top = Math.round(window.screenY + (window.outerHeight - height) / 2);
  return `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no,scrollbars=yes,resizable=yes`;
}

function shouldOpenPopup(response: ConnectResponse): boolean {
  return response.mode === 'popup' && !!response.authorize_url;
}

function extractOAuthMessage(
  event: MessageEvent,
): { key: string; status: string } | null {
  if (
    event.data &&
    typeof event.data === 'object' &&
    event.data.type === 'ayaz-oauth' &&
    typeof event.data.key === 'string' &&
    typeof event.data.status === 'string'
  ) {
    return { key: event.data.key as string, status: event.data.status as string };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Helper to create a synthetic MessageEvent
// ---------------------------------------------------------------------------

function makeMessageEvent(data: unknown): MessageEvent {
  return new MessageEvent('message', { data });
}

// ---------------------------------------------------------------------------
// buildPopupFeatures
// ---------------------------------------------------------------------------

describe('buildPopupFeatures', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('returns a string containing width= and height= with defaults', () => {
    const features = buildPopupFeatures();
    expect(features).toContain('width=600');
    expect(features).toContain('height=720');
  });

  it('respects custom width and height arguments', () => {
    const features = buildPopupFeatures(800, 900);
    expect(features).toContain('width=800');
    expect(features).toContain('height=900');
  });

  it('contains left= and top= positioning keys', () => {
    const features = buildPopupFeatures();
    expect(features).toMatch(/left=\d+/);
    expect(features).toMatch(/top=\d+/);
  });

  it('disables toolbar and menubar', () => {
    const features = buildPopupFeatures();
    expect(features).toContain('toolbar=no');
    expect(features).toContain('menubar=no');
  });

  it('enables scrollbars and resizable', () => {
    const features = buildPopupFeatures();
    expect(features).toContain('scrollbars=yes');
    expect(features).toContain('resizable=yes');
  });

  it('produces a comma-separated key=value string', () => {
    const features = buildPopupFeatures(600, 720);
    const parts = features.split(',');
    // Each part should be key=value
    for (const part of parts) {
      expect(part).toMatch(/^[a-z]+=.+$/);
    }
  });

  it('uses 400×600 when called with those dimensions', () => {
    const features = buildPopupFeatures(400, 600);
    expect(features).toContain('width=400');
    expect(features).toContain('height=600');
  });
});

// ---------------------------------------------------------------------------
// shouldOpenPopup
// ---------------------------------------------------------------------------

describe('shouldOpenPopup', () => {
  it('returns true when mode=popup and authorize_url is present', () => {
    const response: ConnectResponse = {
      mode: 'popup',
      authorize_url: 'https://accounts.google.com/o/oauth2/auth?client_id=abc',
    };
    expect(shouldOpenPopup(response)).toBe(true);
  });

  it('returns false when mode=popup but authorize_url is absent', () => {
    const response: ConnectResponse = { mode: 'popup' };
    expect(shouldOpenPopup(response)).toBe(false);
  });

  it('returns false when mode=popup and authorize_url is empty string', () => {
    const response: ConnectResponse = { mode: 'popup', authorize_url: '' };
    expect(shouldOpenPopup(response)).toBe(false);
  });

  it('returns false when mode=api_key', () => {
    const response: ConnectResponse = {
      mode: 'api_key',
      authorize_url: 'https://example.com/oauth',
    };
    expect(shouldOpenPopup(response)).toBe(false);
  });

  it('returns false when mode=operator_setup_required', () => {
    const response: ConnectResponse = { mode: 'operator_setup_required' };
    expect(shouldOpenPopup(response)).toBe(false);
  });

  it('returns false when mode=operator_setup_required even with an authorize_url', () => {
    const response: ConnectResponse = {
      mode: 'operator_setup_required',
      authorize_url: 'https://example.com/oauth',
    };
    expect(shouldOpenPopup(response)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// extractOAuthMessage
// ---------------------------------------------------------------------------

describe('extractOAuthMessage', () => {
  it('returns parsed data when event.data.type === "ayaz-oauth"', () => {
    const event = makeMessageEvent({
      type: 'ayaz-oauth',
      key: 'meta_ads',
      status: 'connected',
    });
    const result = extractOAuthMessage(event);
    expect(result).not.toBeNull();
    expect(result?.key).toBe('meta_ads');
    expect(result?.status).toBe('connected');
  });

  it('returns null when event.data.type is different', () => {
    const event = makeMessageEvent({ type: 'other-event', key: 'meta_ads', status: 'connected' });
    expect(extractOAuthMessage(event)).toBeNull();
  });

  it('returns null when event.data is null', () => {
    const event = makeMessageEvent(null);
    expect(extractOAuthMessage(event)).toBeNull();
  });

  it('returns null when event.data is a primitive string', () => {
    const event = makeMessageEvent('ayaz-oauth');
    expect(extractOAuthMessage(event)).toBeNull();
  });

  it('returns null when event.data.type is missing', () => {
    const event = makeMessageEvent({ key: 'meta_ads', status: 'connected' });
    expect(extractOAuthMessage(event)).toBeNull();
  });

  it('returns null when key is not a string', () => {
    const event = makeMessageEvent({ type: 'ayaz-oauth', key: 42, status: 'connected' });
    expect(extractOAuthMessage(event)).toBeNull();
  });

  it('returns null when status is not a string', () => {
    const event = makeMessageEvent({ type: 'ayaz-oauth', key: 'meta_ads', status: null });
    expect(extractOAuthMessage(event)).toBeNull();
  });

  it('returns null when event.data is undefined', () => {
    const event = makeMessageEvent(undefined);
    expect(extractOAuthMessage(event)).toBeNull();
  });

  it('returns status=error when OAuth flow failed', () => {
    const event = makeMessageEvent({
      type: 'ayaz-oauth',
      key: 'google_ads',
      status: 'error',
    });
    const result = extractOAuthMessage(event);
    expect(result).not.toBeNull();
    expect(result?.status).toBe('error');
    expect(result?.key).toBe('google_ads');
  });
});

// ---------------------------------------------------------------------------
// Popup open / postMessage integration
// ---------------------------------------------------------------------------

describe('popup OAuth flow — window.open behaviour', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('calls window.open with the authorize_url and "ayaz_oauth" as target when mode=popup', () => {
    const openMock = vi.fn().mockReturnValue({ closed: false });
    vi.stubGlobal('open', openMock);

    const response: ConnectResponse = {
      mode: 'popup',
      authorize_url: 'https://www.facebook.com/dialog/oauth?client_id=123',
    };

    if (shouldOpenPopup(response)) {
      window.open(response.authorize_url!, 'ayaz_oauth', buildPopupFeatures());
    }

    expect(openMock).toHaveBeenCalledOnce();
    const [url, target] = openMock.mock.calls[0] as [string, string, string];
    expect(url).toBe('https://www.facebook.com/dialog/oauth?client_id=123');
    expect(target).toBe('ayaz_oauth');
  });

  it('passes popup feature string containing width= and height= to window.open', () => {
    const openMock = vi.fn().mockReturnValue({ closed: false });
    vi.stubGlobal('open', openMock);

    const response: ConnectResponse = {
      mode: 'popup',
      authorize_url: 'https://accounts.google.com/oauth',
    };

    if (shouldOpenPopup(response)) {
      window.open(response.authorize_url!, 'ayaz_oauth', buildPopupFeatures());
    }

    const [, , features] = openMock.mock.calls[0] as [string, string, string];
    expect(features).toContain('width=');
    expect(features).toContain('height=');
  });

  it('does NOT call window.open when mode=operator_setup_required', () => {
    const openMock = vi.fn();
    vi.stubGlobal('open', openMock);

    const response: ConnectResponse = { mode: 'operator_setup_required' };

    if (shouldOpenPopup(response)) {
      window.open('https://example.com', 'ayaz_oauth', buildPopupFeatures());
    }

    expect(openMock).not.toHaveBeenCalled();
  });

  it('does NOT call window.open when mode=api_key', () => {
    const openMock = vi.fn();
    vi.stubGlobal('open', openMock);

    const response: ConnectResponse = { mode: 'api_key' };

    if (shouldOpenPopup(response)) {
      window.open('https://example.com', 'ayaz_oauth', buildPopupFeatures());
    }

    expect(openMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// postMessage handler — success callback trigger
// ---------------------------------------------------------------------------

describe('postMessage handler', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('triggers the success callback when MessageEvent has type=ayaz-oauth and status=connected', () => {
    const successCallback = vi.fn();

    function handleMessage(event: MessageEvent): void {
      const parsed = extractOAuthMessage(event);
      if (parsed && parsed.status === 'connected') {
        successCallback(parsed.key);
      }
    }

    const event = makeMessageEvent({
      type: 'ayaz-oauth',
      key: 'meta_ads',
      status: 'connected',
    });

    handleMessage(event);

    expect(successCallback).toHaveBeenCalledOnce();
    expect(successCallback).toHaveBeenCalledWith('meta_ads');
  });

  it('does NOT trigger the success callback for unrelated messages', () => {
    const successCallback = vi.fn();

    function handleMessage(event: MessageEvent): void {
      const parsed = extractOAuthMessage(event);
      if (parsed && parsed.status === 'connected') {
        successCallback(parsed.key);
      }
    }

    handleMessage(makeMessageEvent({ type: 'webpack-hmr', data: 'ok' }));
    handleMessage(makeMessageEvent(null));
    handleMessage(makeMessageEvent('string payload'));

    expect(successCallback).not.toHaveBeenCalled();
  });

  it('does NOT trigger the success callback when status is error', () => {
    const successCallback = vi.fn();
    const errorCallback = vi.fn();

    function handleMessage(event: MessageEvent): void {
      const parsed = extractOAuthMessage(event);
      if (!parsed) return;
      if (parsed.status === 'connected') {
        successCallback(parsed.key);
      } else {
        errorCallback(parsed.status);
      }
    }

    handleMessage(
      makeMessageEvent({ type: 'ayaz-oauth', key: 'google_ads', status: 'error' }),
    );

    expect(successCallback).not.toHaveBeenCalled();
    expect(errorCallback).toHaveBeenCalledWith('error');
  });

  it('resolves a Promise when the OAuth postMessage arrives', async () => {
    const promise = new Promise<string>((resolve) => {
      function handler(event: MessageEvent): void {
        const parsed = extractOAuthMessage(event);
        if (parsed && parsed.status === 'connected') {
          window.removeEventListener('message', handler);
          resolve(parsed.key);
        }
      }
      window.addEventListener('message', handler);
    });

    // Simulate the popup posting back to the opener
    const event = makeMessageEvent({ type: 'ayaz-oauth', key: 'tiktok_ads', status: 'connected' });
    window.dispatchEvent(event);

    const key = await promise;
    expect(key).toBe('tiktok_ads');
  });
});
