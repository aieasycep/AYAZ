import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { formatRelativeTr } from '@/components/NotificationBell';

// ---------------------------------------------------------------------------
// Fixed "now": 2026-03-15 14:00:00 UTC
// We freeze Date.now() so every call to formatRelativeTr is deterministic.
// ---------------------------------------------------------------------------

const NOW_ISO = '2026-03-15T14:00:00.000Z';
const NOW_MS = new Date(NOW_ISO).getTime();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW_MS);
});

afterEach(() => {
  vi.useRealTimers();
});

// Helper: NOW minus N seconds
function secsAgo(n: number): string {
  return new Date(NOW_MS - n * 1000).toISOString();
}

describe('formatRelativeTr', () => {
  it('returns "az önce" for timestamps less than 60 seconds ago', () => {
    expect(formatRelativeTr(secsAgo(30))).toBe('az önce');
    expect(formatRelativeTr(secsAgo(59))).toBe('az önce');
    // exactly 0 seconds ago
    expect(formatRelativeTr(secsAgo(0))).toBe('az önce');
  });

  it('returns "X dakika önce" for 1–59 minutes ago', () => {
    expect(formatRelativeTr(secsAgo(60))).toBe('1 dakika önce');
    expect(formatRelativeTr(secsAgo(5 * 60))).toBe('5 dakika önce');
    expect(formatRelativeTr(secsAgo(59 * 60))).toBe('59 dakika önce');
  });

  it('returns "X saat önce" for 1–23 hours ago', () => {
    expect(formatRelativeTr(secsAgo(60 * 60))).toBe('1 saat önce');
    expect(formatRelativeTr(secsAgo(6 * 60 * 60))).toBe('6 saat önce');
    expect(formatRelativeTr(secsAgo(23 * 60 * 60))).toBe('23 saat önce');
  });

  it('returns "dün" for timestamps 24–47 hours ago', () => {
    expect(formatRelativeTr(secsAgo(24 * 60 * 60))).toBe('dün');
    expect(formatRelativeTr(secsAgo(47 * 60 * 60))).toBe('dün');
  });

  it('returns DD.MM.YYYY for timestamps 48+ hours ago', () => {
    // 48 hours ago from 2026-03-15T14:00:00Z = 2026-03-13T14:00:00Z → "13.03.2026"
    const old = secsAgo(48 * 60 * 60);
    expect(formatRelativeTr(old)).toBe('13.03.2026');
  });

  it('returns DD.MM.YYYY for a specific known-old date', () => {
    expect(formatRelativeTr('2025-06-01T00:00:00.000Z')).toBe('01.06.2025');
  });
});
