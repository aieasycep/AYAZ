// Client-side CSV export utility.
//
// Converts an array of plain row objects into an RFC 4180 CSV string and
// triggers a browser download — no backend call, no new dependency.
// This is intentionally separate from `downloadCsv` in `./api.ts`, which
// hits an authenticated backend export endpoint; this util only ever
// serializes data that is *already* loaded into component state.

export interface CsvColumn {
  key: string;
  label: string;
}

// UTF-8 BOM so Excel (Windows) detects the encoding and renders Turkish
// characters (ç, ğ, ı, ö, ş, ü) correctly instead of mangling them.
const UTF8_BOM = '﻿';

/**
 * Escape a single CSV field per RFC 4180: wrap in double quotes if the value
 * contains a comma, double quote, or newline, and double any inner quotes.
 */
function escapeCsvField(value: unknown): string {
  let str: string;
  if (value === null || value === undefined) {
    str = '';
  } else if (typeof value === 'number' || typeof value === 'boolean') {
    str = String(value);
  } else {
    str = String(value);
  }

  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

function buildCsv(
  rows: Record<string, unknown>[],
  columns?: CsvColumn[],
): string {
  const cols: CsvColumn[] =
    columns ?? Object.keys(rows[0] ?? {}).map((key) => ({ key, label: key }));

  const headerLine = cols.map((c) => escapeCsvField(c.label)).join(',');
  const lines = rows.map((row) =>
    cols.map((c) => escapeCsvField(row[c.key])).join(','),
  );

  return [headerLine, ...lines].join('\r\n');
}

/**
 * Serialize `rows` to CSV and trigger a browser download named `filename`.
 *
 * - `columns` (optional) controls column order/labels and which keys are
 *   included. When omitted, columns are derived from the first row's keys
 *   (insertion order), and labels equal the keys.
 * - When `rows` is empty and `columns` is provided, a header-only CSV is
 *   downloaded. When `rows` is empty and no `columns` are given, this is a
 *   safe no-op (nothing to derive headers from).
 * - No-op outside the browser (e.g. SSR) since there is no DOM to append
 *   the temporary `<a>` to.
 */
export function downloadRowsAsCsv(
  rows: Record<string, unknown>[],
  filename: string,
  columns?: CsvColumn[],
): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (rows.length === 0 && !columns) return;

  const csv = buildCsv(rows, columns);
  const blob = new Blob([UTF8_BOM + csv], { type: 'text/csv;charset=utf-8;' });

  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(objectUrl);
}
