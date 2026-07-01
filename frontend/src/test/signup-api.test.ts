import { describe, it, expect, vi, afterEach } from 'vitest';
import { signup } from '@/lib/api';
import type { SignupPayload } from '@/lib/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePayload(overrides: Partial<SignupPayload> = {}): SignupPayload {
  return {
    email: 'test@example.com',
    password: 'password123',
    org_name: 'Test Org',
    ...overrides,
  };
}

function mockFetch(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
      text: () => Promise.resolve(typeof body === 'string' ? body : JSON.stringify(body)),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// signup() — happy path
// ---------------------------------------------------------------------------

describe('signup — happy path', () => {
  it('returns access_token and token_type on 201', async () => {
    mockFetch(201, { access_token: 'tok_abc', token_type: 'bearer' });

    const result = await signup(makePayload());

    expect(result.access_token).toBe('tok_abc');
    expect(result.token_type).toBe('bearer');
  });

  it('sends the correct JSON payload including org_name', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ access_token: 'tok', token_type: 'bearer' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await signup(makePayload({ full_name: 'Ada Yılmaz', org_name: 'Ajans Ltd' }));

    expect(fetchMock).toHaveBeenCalledOnce();
    const [_url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.org_name).toBe('Ajans Ltd');
    expect(body.full_name).toBe('Ada Yılmaz');
    expect(body.email).toBe('test@example.com');
    expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' });
  });

  it('omits full_name from payload when not provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ access_token: 'tok', token_type: 'bearer' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const payload = makePayload();
    delete payload.full_name;
    await signup(payload);

    const [_url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect('full_name' in body).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// signup() — error handling
// ---------------------------------------------------------------------------

describe('signup — error handling', () => {
  it('throws with backend detail string on 409 duplicate email', async () => {
    mockFetch(409, { detail: 'Bu e-posta adresi zaten kullanımda.' });

    await expect(signup(makePayload())).rejects.toThrow(
      'Bu e-posta adresi zaten kullanımda.',
    );
  });

  it('flattens 422 FastAPI errors array to the first .msg', async () => {
    mockFetch(422, {
      detail: [
        { loc: ['body', 'password'], msg: 'Şifre en az 8 karakter olmalıdır.', type: 'value_error' },
        { loc: ['body', 'org_name'], msg: 'Bu alan zorunludur.', type: 'value_error' },
      ],
    });

    await expect(signup(makePayload())).rejects.toThrow(
      'Şifre en az 8 karakter olmalıdır.',
    );
  });

  it('uses generic fallback message when 422 detail array is empty', async () => {
    mockFetch(422, { detail: [] });

    await expect(signup(makePayload())).rejects.toThrow('Kayıt başarısız');
  });

  it('throws with detail string on 429 rate limit', async () => {
    mockFetch(429, { detail: 'Çok fazla istek gönderildi.' });

    await expect(signup(makePayload())).rejects.toThrow(
      'Çok fazla istek gönderildi.',
    );
  });

  it('uses generic fallback when error body cannot be parsed as JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.reject(new SyntaxError('bad json')),
        text: () => Promise.resolve('Internal Server Error'),
      }),
    );

    await expect(signup(makePayload())).rejects.toThrow('Kayıt başarısız');
  });

  it('does not call setToken — token storage is the caller\'s responsibility', async () => {
    mockFetch(201, { access_token: 'tok_abc', token_type: 'bearer' });

    // Ensure localStorage is not written by signup() itself
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem');
    await signup(makePayload());
    expect(setItemSpy).not.toHaveBeenCalled();
    setItemSpy.mockRestore();
  });
});
