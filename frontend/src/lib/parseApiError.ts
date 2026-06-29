/**
 * parseApiError — converts any thrown value into a clean, human-readable
 * Turkish error message.
 *
 * Rules:
 * 1. Network / offline errors → "Bağlantı kurulamadı. Lütfen tekrar deneyin."
 * 2. A string that looks like a JSON blob (e.g. `{"detail":"..."}`) →
 *    extract the `detail` or `error` field and use it IF it is already a
 *    plain Turkish/human string (not another JSON object).
 * 3. A plain string (already a human message) → return as-is.
 * 4. A Response object or anything else → generic Turkish fallback.
 *
 * NEVER returns JSON.stringify output or a raw `{"detail":...}` string.
 */
export function parseApiError(err: unknown): string {
  // ── 1. Network / fetch failure ───────────────────────────────────────────
  if (err instanceof TypeError && err.message.toLowerCase().includes('fetch')) {
    return 'Bağlantı kurulamadı. Lütfen tekrar deneyin.';
  }

  // ── 2. Error objects (the most common case from our authFetch wrappers) ──
  if (err instanceof Error) {
    return extractHuman(err.message);
  }

  // ── 3. Raw string ────────────────────────────────────────────────────────
  if (typeof err === 'string') {
    return extractHuman(err);
  }

  // ── 4. Fallback ──────────────────────────────────────────────────────────
  return 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';
}

/**
 * Given a string that may be:
 *   - a raw JSON blob: `{"detail":"Some message"}` or `{"error":"..."}`
 *   - a plain human sentence
 * Returns the clean human text, or the generic fallback.
 */
function extractHuman(raw: string): string {
  const trimmed = (raw ?? '').trim();
  if (!trimmed) return 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';

  // Looks like it might be JSON?
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;

      // FastAPI detail as a plain string
      if (typeof parsed.detail === 'string') {
        const detail = parsed.detail.trim();
        // If the detail is ITSELF a JSON blob, don't surface it — use generic
        if (detail.startsWith('{') || detail.startsWith('[')) {
          return 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';
        }
        return detail || 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';
      }

      // FastAPI validation errors array
      if (Array.isArray(parsed.detail)) {
        const first = parsed.detail[0] as Record<string, unknown> | undefined;
        if (first && typeof first.msg === 'string') {
          return first.msg.trim() || 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';
        }
      }

      // Generic `error` field
      if (typeof parsed.error === 'string') {
        const errText = parsed.error.trim();
        if (errText.startsWith('{') || errText.startsWith('[')) {
          return 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';
        }
        return errText || 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';
      }

      // `message` field
      if (typeof parsed.message === 'string') {
        return parsed.message.trim() || 'Bir şeyler ters gitti. Lütfen tekrar deneyin.';
      }
    } catch {
      // Not valid JSON — treat as plain text below
    }
  }

  // Plain text message — return as-is if it seems human-readable
  // (not a raw technical string like "NetworkError" or a stack trace)
  return trimmed;
}
