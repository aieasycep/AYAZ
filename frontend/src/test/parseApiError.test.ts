import { describe, it, expect, vi, afterEach } from 'vitest';
import { parseApiError } from '@/lib/parseApiError';

// Mirrors the Error shape thrown by our authFetch helpers: a normal Error
// with an optional `.status` carrying the HTTP status code.
function apiError(message: string, status?: number): Error {
  const err = new Error(message) as Error & { status?: number };
  if (status !== undefined) err.status = status;
  return err;
}

describe('parseApiError', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  // ── Network / offline ────────────────────────────────────────────────

  it('returns the offline message for a TypeError thrown by fetch()', () => {
    const err = new TypeError('Failed to fetch');
    expect(parseApiError(err)).toBe(
      'Çevrimdışısınız. Lütfen bağlantınızı kontrol edin.',
    );
  });

  it('returns the offline message for any TypeError regardless of wording', () => {
    const err = new TypeError('NetworkError when attempting to fetch resource');
    expect(parseApiError(err)).toBe(
      'Çevrimdışısınız. Lütfen bağlantınızı kontrol edin.',
    );
  });

  it('returns the offline message when navigator.onLine is false, even for a regular Error', () => {
    vi.stubGlobal('navigator', { onLine: false });
    const err = apiError('{"detail":"some backend detail"}', 500);
    expect(parseApiError(err)).toBe(
      'Çevrimdışısınız. Lütfen bağlantınızı kontrol edin.',
    );
  });

  it('does NOT show the offline message for a 5xx error when online', () => {
    vi.stubGlobal('navigator', { onLine: true });
    const err = apiError('Internal Server Error', 500);
    expect(parseApiError(err)).not.toBe(
      'Çevrimdışısınız. Lütfen bağlantınızı kontrol edin.',
    );
  });

  // ── 5xx → generic server message ────────────────────────────────────

  it('returns the server-error message for a 500 status', () => {
    const err = apiError('{"detail":"Traceback (most recent call last)..."}', 500);
    expect(parseApiError(err)).toBe(
      'Sunucuya ulaşılamadı. Lütfen birazdan tekrar deneyin.',
    );
  });

  it('returns the server-error message for a 502/503/504 status', () => {
    expect(parseApiError(apiError('Bad Gateway', 502))).toBe(
      'Sunucuya ulaşılamadı. Lütfen birazdan tekrar deneyin.',
    );
    expect(parseApiError(apiError('Service Unavailable', 503))).toBe(
      'Sunucuya ulaşılamadı. Lütfen birazdan tekrar deneyin.',
    );
    expect(parseApiError(apiError('Gateway Timeout', 504))).toBe(
      'Sunucuya ulaşılamadı. Lütfen birazdan tekrar deneyin.',
    );
  });

  it('never leaks raw JSON onto the screen for a 5xx error', () => {
    const err = apiError('{"error":"Çevrimdışısınız. Lütfen bağlantınızı kontrol edin."}', 503);
    const result = parseApiError(err);
    expect(result).not.toContain('{');
    expect(result).not.toContain('}');
    expect(result).toBe('Sunucuya ulaşılamadı. Lütfen birazdan tekrar deneyin.');
  });

  // ── 4xx → parsed, human-readable detail ─────────────────────────────

  it('returns the parsed `detail` string for a 4xx error', () => {
    const err = apiError('{"detail":"Bu kampanya zaten mevcut."}', 409);
    expect(parseApiError(err)).toBe('Bu kampanya zaten mevcut.');
  });

  it('returns the first validation message for a 422 FastAPI error array', () => {
    const err = apiError(
      '{"detail":[{"loc":["body","email"],"msg":"Geçersiz e-posta adresi","type":"value_error"}]}',
      422,
    );
    expect(parseApiError(err)).toBe('Geçersiz e-posta adresi');
  });

  it('returns the parsed `error` field for a 4xx error', () => {
    const err = apiError('{"error":"Bu işlem için yetkiniz yok."}', 403);
    expect(parseApiError(err)).toBe('Bu işlem için yetkiniz yok.');
  });

  it('returns the parsed `message` field for a 4xx error', () => {
    const err = apiError('{"message":"İstek geçersiz."}', 400);
    expect(parseApiError(err)).toBe('İstek geçersiz.');
  });

  it('never returns a raw JSON string for a 4xx error', () => {
    const err = apiError('{"detail":"Kayıt bulunamadı."}', 404);
    const result = parseApiError(err);
    expect(result).not.toMatch(/^\{.*\}$/);
    expect(result).toBe('Kayıt bulunamadı.');
  });

  it('returns the generic fallback if a 4xx body is JSON but has no recognizable field', () => {
    const err = apiError('{"code":"E_UNKNOWN"}', 400);
    expect(parseApiError(err)).toBe('Bir şeyler ters gitti. Lütfen tekrar deneyin.');
  });

  it('returns a plain-text 4xx body as-is when it is not JSON', () => {
    const err = apiError('Geçersiz istek.', 400);
    expect(parseApiError(err)).toBe('Geçersiz istek.');
  });

  // ── No status attached (e.g. "Oturum süresi doldu") ─────────────────

  it('passes through a plain Error message with no status untouched', () => {
    const err = apiError('Oturum süresi doldu');
    expect(parseApiError(err)).toBe('Oturum süresi doldu');
  });

  // ── Non-Error inputs ─────────────────────────────────────────────────

  it('parses a raw JSON string input the same way as an Error message', () => {
    expect(parseApiError('{"detail":"Şifre çok kısa."}')).toBe('Şifre çok kısa.');
  });

  it('returns the generic fallback for completely unknown thrown values', () => {
    expect(parseApiError(undefined)).toBe('Bir şeyler ters gitti. Lütfen tekrar deneyin.');
    expect(parseApiError(null)).toBe('Bir şeyler ters gitti. Lütfen tekrar deneyin.');
    expect(parseApiError({ some: 'object' })).toBe(
      'Bir şeyler ters gitti. Lütfen tekrar deneyin.',
    );
  });

  it('returns the generic fallback when the detail field is itself a nested JSON blob', () => {
    const err = apiError('{"detail":"{\\"nested\\":true}"}', 400);
    expect(parseApiError(err)).toBe('Bir şeyler ters gitti. Lütfen tekrar deneyin.');
  });
});
