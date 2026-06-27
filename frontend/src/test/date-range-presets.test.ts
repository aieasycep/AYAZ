import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  toLocalISODate,
  computePreset,
  detectPreset,
} from '@/components/DateRangePresets';

// ---------------------------------------------------------------------------
// Fixed reference date: 2026-03-15 (a Saturday, mid-month)
// Using vi.useFakeTimers so every `new Date()` call inside the helpers returns
// a deterministic local time. We set the system time to noon to avoid any
// midnight edge-cases around DST.
// ---------------------------------------------------------------------------

const FIXED_DATE_ISO = '2026-03-15T12:00:00';

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(FIXED_DATE_ISO));
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// toLocalISODate
// ---------------------------------------------------------------------------

describe('toLocalISODate', () => {
  it('formats a date with zero-padded month and day', () => {
    expect(toLocalISODate(new Date('2026-01-05T00:00:00'))).toBe('2026-01-05');
  });

  it('formats a date at end of year', () => {
    expect(toLocalISODate(new Date('2026-12-31T00:00:00'))).toBe('2026-12-31');
  });
});

// ---------------------------------------------------------------------------
// computePreset — fixed reference date 2026-03-15
// ---------------------------------------------------------------------------

describe('computePreset', () => {
  it('son7 — last 7 days inclusive (today − 6 through today)', () => {
    const { from, to } = computePreset('son7');
    expect(from).toBe('2026-03-09');
    expect(to).toBe('2026-03-15');
  });

  it('son30 — last 30 days inclusive (today − 29 through today)', () => {
    const { from, to } = computePreset('son30');
    expect(from).toBe('2026-02-14');
    expect(to).toBe('2026-03-15');
  });

  it('son90 — last 90 days inclusive (today − 89 through today)', () => {
    const { from, to } = computePreset('son90');
    expect(from).toBe('2025-12-16');
    expect(to).toBe('2026-03-15');
  });

  it('buAy — first of current month through today', () => {
    const { from, to } = computePreset('buAy');
    expect(from).toBe('2026-03-01');
    expect(to).toBe('2026-03-15');
  });

  it('gecenAy — full previous month (February 2026, not a leap-year edge case)', () => {
    // March 2026 → prev month is February 2026 (28 days)
    const { from, to } = computePreset('gecenAy');
    expect(from).toBe('2026-02-01');
    expect(to).toBe('2026-02-28');
  });
});

// ---------------------------------------------------------------------------
// gecenAy — edge case: January (previous month is December of prev year)
// ---------------------------------------------------------------------------

describe('computePreset gecenAy — year boundary', () => {
  it('returns December of the previous year when today is in January', () => {
    vi.setSystemTime(new Date('2026-01-10T12:00:00'));
    const { from, to } = computePreset('gecenAy');
    expect(from).toBe('2025-12-01');
    expect(to).toBe('2025-12-31');
  });
});

// ---------------------------------------------------------------------------
// detectPreset — round-trip
// ---------------------------------------------------------------------------

describe('detectPreset', () => {
  it('returns the correct key for son7', () => {
    const { from, to } = computePreset('son7');
    expect(detectPreset(from, to)).toBe('son7');
  });

  it('returns the correct key for son30', () => {
    const { from, to } = computePreset('son30');
    expect(detectPreset(from, to)).toBe('son30');
  });

  it('returns the correct key for buAy', () => {
    const { from, to } = computePreset('buAy');
    expect(detectPreset(from, to)).toBe('buAy');
  });

  it('returns the correct key for gecenAy', () => {
    const { from, to } = computePreset('gecenAy');
    expect(detectPreset(from, to)).toBe('gecenAy');
  });

  it('returns null for an arbitrary range that matches no preset', () => {
    expect(detectPreset('2024-01-01', '2024-06-30')).toBeNull();
  });
});
