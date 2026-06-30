/**
 * parseApiError — converts any thrown value into a clean, human-readable
 * Turkish error message.
 *
 * Rules (checked in this order):
 * 1. A genuine network/offline failure — either `fetch()` itself rejected
 *    (TypeError, e.g. DNS/connection failure) or the browser reports
 *    `navigator.onLine === false` — →
 *    "Çevrimdışısınız. Lütfen bağlantınızı kontrol edin."
 * 2. An HTTP error with status >= 500 (server reachable but failing) →
 *    "Sunucuya ulaşılamadı. Lütfen birazdan tekrar deneyin."
 * 3. An HTTP error with a 4xx status → the parsed, human-readable
 *    `detail` / `message` / `error` field from the API response body
 *    (never the raw JSON string).
 * 4. Anything else (string, unknown object, no status attached, etc.) →
 *    best-effort parse of the message content, falling back to a generic
 *    Turkish message.
 *
 * NEVER returns JSON.stringify output or a raw `{"detail":...}` string —
 * every branch returns plain, displayable text.
 */

const OFFLINE_MESSAGE = 'Çevrimdışısınız. Lütfen bağlantınızı kontrol edin.';
const SERVER_ERROR_MESSAGE = 'Sunucuya ulaşılamadı. Lütfen birazdan tekrar deneyin.';
const GENERIC_MESSAGE = 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';

/**
 * Shape of the Error our `authFetch` helpers throw: a normal Error with an
 * optional `.status` carrying the HTTP status code of the failed response.
 * `status` is absent for genuine network failures (the request never made it
 * to a server, e.g. `fetch()` rejected before any Response existed).
 */
type ApiErrorLike = Error & { status?: number };

function hasStatus(err: Error): err is ApiErrorLike & { status: number } {
  return typeof (err as ApiErrorLike).status === 'number';
}

export function parseApiError(err: unknown): string {
  // ── 1a. Browser-level network failure (fetch() itself rejected) ────────
  // A TypeError from fetch (e.g. "Failed to fetch", "NetworkError when
  // attempting to fetch resource") means the request never reached a server.
  if (err instanceof TypeError) {
    return OFFLINE_MESSAGE;
  }

  // ── 1b. Explicit offline signal from the browser ────────────────────────
  if (
    typeof navigator !== 'undefined' &&
    'onLine' in navigator &&
    navigator.onLine === false
  ) {
    return OFFLINE_MESSAGE;
  }

  // ── 2 & 3. Error objects from our authFetch wrappers (carry .status) ───
  if (err instanceof Error) {
    if (hasStatus(err) && err.status >= 500) {
      return SERVER_ERROR_MESSAGE;
    }
    // 4xx (or no status attached) — surface the parsed, human detail text.
    return extractHuman(err.message);
  }

  // ── 4. Raw string ────────────────────────────────────────────────────
  if (typeof err === 'string') {
    return extractHuman(err);
  }

  // ── 5. Fallback ──────────────────────────────────────────────────────
  return GENERIC_MESSAGE;
}

/**
 * Given a string that may be:
 *   - a raw JSON blob: `{"detail":"Some message"}` or `{"error":"..."}`
 *   - a plain human sentence
 * Returns the clean human text, or the generic fallback.
 */
function extractHuman(raw: string): string {
  const trimmed = (raw ?? '').trim();
  if (!trimmed) return GENERIC_MESSAGE;

  // Looks like it might be JSON?
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;

      // FastAPI detail as a plain string
      if (typeof parsed.detail === 'string') {
        const detail = parsed.detail.trim();
        // If the detail is ITSELF a JSON blob, don't surface it — use generic
        if (detail.startsWith('{') || detail.startsWith('[')) {
          return GENERIC_MESSAGE;
        }
        return detail || GENERIC_MESSAGE;
      }

      // FastAPI validation errors array
      if (Array.isArray(parsed.detail)) {
        const first = parsed.detail[0] as Record<string, unknown> | undefined;
        if (first && typeof first.msg === 'string') {
          return first.msg.trim() || GENERIC_MESSAGE;
        }
        return GENERIC_MESSAGE;
      }

      // Generic `error` field — this is also how the offline service-worker
      // fallback response is shaped: { error: "Çevrimdışısınız..." }. When
      // present (and not itself JSON), surface it as-is — it is already a
      // clean Turkish sentence.
      if (typeof parsed.error === 'string') {
        const errText = parsed.error.trim();
        if (errText.startsWith('{') || errText.startsWith('[')) {
          return GENERIC_MESSAGE;
        }
        return errText || GENERIC_MESSAGE;
      }

      // `message` field
      if (typeof parsed.message === 'string') {
        return parsed.message.trim() || GENERIC_MESSAGE;
      }

      // Valid JSON, but none of the known human-message fields were present
      // — never surface the raw JSON blob itself.
      return GENERIC_MESSAGE;
    } catch {
      // Not valid JSON — treat as plain text below
    }
  }

  // Plain text message — return as-is if it seems human-readable
  // (not a raw technical string like "NetworkError" or a stack trace)
  return trimmed;
}
