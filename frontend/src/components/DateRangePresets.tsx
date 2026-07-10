'use client';

// ---------------------------------------------------------------------------
// Date math helpers — pure functions, no external deps, local time only.
// Exported so pages can detect which preset matches the current applied range.
// ---------------------------------------------------------------------------

/** Format a Date as YYYY-MM-DD using local time (never UTC). */
export function toLocalISODate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export type PresetKey =
  | 'son7'
  | 'son30'
  | 'son90'
  | 'son6ay'
  | 'son12ay'
  | 'buAy'
  | 'gecenAy';

export interface PresetRange {
  from: string;
  to: string;
}

/** Compute the YYYY-MM-DD range for a given preset, relative to today (local time). */
export function computePreset(preset: PresetKey): PresetRange {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  switch (preset) {
    case 'son7': {
      const from = new Date(today);
      from.setDate(from.getDate() - 6);
      return { from: toLocalISODate(from), to: toLocalISODate(today) };
    }
    case 'son30': {
      const from = new Date(today);
      from.setDate(from.getDate() - 29);
      return { from: toLocalISODate(from), to: toLocalISODate(today) };
    }
    case 'son90': {
      const from = new Date(today);
      from.setDate(from.getDate() - 89);
      return { from: toLocalISODate(from), to: toLocalISODate(today) };
    }
    case 'son6ay': {
      const from = new Date(today);
      from.setDate(from.getDate() - 179);
      return { from: toLocalISODate(from), to: toLocalISODate(today) };
    }
    case 'son12ay': {
      const from = new Date(today);
      from.setDate(from.getDate() - 364);
      return { from: toLocalISODate(from), to: toLocalISODate(today) };
    }
    case 'buAy': {
      const from = new Date(today.getFullYear(), today.getMonth(), 1);
      return { from: toLocalISODate(from), to: toLocalISODate(today) };
    }
    case 'gecenAy': {
      const firstOfThisMonth = new Date(today.getFullYear(), today.getMonth(), 1);
      const lastOfPrevMonth = new Date(firstOfThisMonth.getTime() - 1);
      lastOfPrevMonth.setHours(0, 0, 0, 0);
      const firstOfPrevMonth = new Date(
        lastOfPrevMonth.getFullYear(),
        lastOfPrevMonth.getMonth(),
        1,
      );
      return {
        from: toLocalISODate(firstOfPrevMonth),
        to: toLocalISODate(lastOfPrevMonth),
      };
    }
  }
}

/**
 * Given a from+to pair, returns the matching PresetKey or null if none match.
 * Computed fresh each call so it always reflects "today".
 */
export function detectPreset(from: string, to: string): PresetKey | null {
  const presets: PresetKey[] = [
    'son7',
    'son30',
    'son90',
    'son6ay',
    'son12ay',
    'buAy',
    'gecenAy',
  ];
  for (const key of presets) {
    const range = computePreset(key);
    if (range.from === from && range.to === to) return key;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const PRESETS: { key: PresetKey; label: string }[] = [
  { key: 'son7', label: 'Son 7 gün' },
  { key: 'son30', label: 'Son 30 gün' },
  { key: 'son90', label: 'Son 90 gün' },
  { key: 'son6ay', label: 'Son 6 ay' },
  { key: 'son12ay', label: 'Son 12 ay' },
  { key: 'buAy', label: 'Bu ay' },
  { key: 'gecenAy', label: 'Geçen ay' },
];

interface DateRangePresetsProps {
  /** Called with YYYY-MM-DD strings when user clicks a preset. */
  onSelect: (from: string, to: string) => void;
  /** The currently active preset key, if any. Pass null/undefined for none. */
  activePreset?: PresetKey | null;
}

import styles from './DateRangePresets.module.css';

export default function DateRangePresets({
  onSelect,
  activePreset,
}: DateRangePresetsProps) {
  function handleClick(key: PresetKey) {
    const range = computePreset(key);
    onSelect(range.from, range.to);
  }

  return (
    <div className={styles.presetRow} role="group" aria-label="Hızlı tarih aralığı seçimi">
      {PRESETS.map(({ key, label }) => {
        const isActive = activePreset === key;
        return (
          <button
            key={key}
            type="button"
            className={`${styles.presetBtn} ${isActive ? styles.presetBtnActive : ''}`}
            aria-pressed={isActive}
            onClick={() => handleClick(key)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
