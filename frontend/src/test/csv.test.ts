import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { downloadRowsAsCsv } from '@/lib/csv';

// jsdom does not implement URL.createObjectURL/revokeObjectURL, so we stub
// them to capture the Blob that downloadRowsAsCsv() builds, and read its
// text back out via Blob#text() (available in jsdom's Blob polyfill).
describe('downloadRowsAsCsv', () => {
  let createObjectURLSpy: ReturnType<typeof vi.fn<(blob: Blob) => string>>;
  let revokeObjectURLSpy: ReturnType<typeof vi.fn<(url: string) => void>>;
  let capturedBlob: Blob | null;
  let clickSpy: ReturnType<typeof vi.fn<() => void>>;
  let capturedAnchor: { href: string; download: string } | null;

  beforeEach(() => {
    capturedBlob = null;
    capturedAnchor = null;

    createObjectURLSpy = vi.fn((blob: Blob) => {
      capturedBlob = blob;
      return 'blob:mock-url';
    });
    revokeObjectURLSpy = vi.fn();

    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: createObjectURLSpy,
      revokeObjectURL: revokeObjectURLSpy,
    });

    clickSpy = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = originalCreateElement(tag);
      if (tag === 'a') {
        const anchor = el as HTMLAnchorElement;
        vi.spyOn(anchor, 'click').mockImplementation(() => {
          clickSpy();
          capturedAnchor = { href: anchor.href, download: anchor.download };
        });
      }
      return el;
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function captureCsvText(): Promise<string> {
    expect(capturedBlob).not.toBeNull();
    return capturedBlob!.text();
  }

  // ── Basic shape ──────────────────────────────────────────────────────

  it('writes a header row from columns and one line per row', async () => {
    downloadRowsAsCsv(
      [
        { channel: 'meta', spend: 100 },
        { channel: 'google', spend: 200 },
      ],
      'test.csv',
      [
        { key: 'channel', label: 'Kanal' },
        { key: 'spend', label: 'Harcama' },
      ],
    );

    const text = await captureCsvText();
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines[0]).toBe('Kanal,Harcama');
    expect(lines[1]).toBe('meta,100');
    expect(lines[2]).toBe('google,200');
  });

  it('derives headers from the first row keys when columns are omitted', async () => {
    downloadRowsAsCsv([{ a: 1, b: 'x' }, { a: 2, b: 'y' }], 'test.csv');
    const text = await captureCsvText();
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines[0]).toBe('a,b');
    expect(lines[1]).toBe('1,x');
  });

  it('triggers a download via a temporary <a download> click', () => {
    downloadRowsAsCsv([{ a: 1 }], 'my-export.csv');
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url');
  });

  // ── RFC 4180 escaping ────────────────────────────────────────────────

  it('wraps a field containing a comma in double quotes', async () => {
    downloadRowsAsCsv([{ label: 'Meta, Google' }], 'test.csv', [
      { key: 'label', label: 'Etiket' },
    ]);
    const text = await captureCsvText();
    expect(text).toContain('"Meta, Google"');
  });

  it('doubles internal double quotes and wraps the field', async () => {
    downloadRowsAsCsv([{ label: 'Bir "harika" kanal' }], 'test.csv', [
      { key: 'label', label: 'Etiket' },
    ]);
    const text = await captureCsvText();
    expect(text).toContain('"Bir ""harika"" kanal"');
  });

  it('wraps a field containing a newline in double quotes', async () => {
    downloadRowsAsCsv([{ note: 'satır 1\nsatır 2' }], 'test.csv', [
      { key: 'note', label: 'Not' },
    ]);
    const text = await captureCsvText();
    expect(text).toContain('"satır 1\nsatır 2"');
  });

  it('does not quote plain alphanumeric fields', async () => {
    downloadRowsAsCsv([{ channel: 'meta' }], 'test.csv', [
      { key: 'channel', label: 'Kanal' },
    ]);
    const text = await captureCsvText();
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines[1]).toBe('meta');
  });

  // ── BOM ──────────────────────────────────────────────────────────────

  it('prefixes the CSV with a UTF-8 BOM for Excel compatibility', async () => {
    downloadRowsAsCsv([{ label: 'ığüşöç' }], 'test.csv', [
      { key: 'label', label: 'Etiket' },
    ]);
    expect(capturedBlob).not.toBeNull();
    // Blob#text() decodes as UTF-8 and strips a leading BOM (per the
    // TextDecoder spec), so assert on the raw bytes instead: EF BB BF.
    const buf = await capturedBlob!.arrayBuffer();
    const bytes = new Uint8Array(buf).slice(0, 3);
    expect(Array.from(bytes)).toEqual([0xef, 0xbb, 0xbf]);

    const text = await captureCsvText();
    expect(text).toContain('ığüşöç');
  });

  // ── null / undefined / number / boolean coercion ────────────────────

  it('renders null and undefined as empty strings', async () => {
    downloadRowsAsCsv(
      [{ a: null, b: undefined, c: 'x' }],
      'test.csv',
      [
        { key: 'a', label: 'A' },
        { key: 'b', label: 'B' },
        { key: 'c', label: 'C' },
      ],
    );
    const text = await captureCsvText();
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines[1]).toBe(',,x');
  });

  it('renders numbers and booleans as their string form', async () => {
    downloadRowsAsCsv(
      [{ n: 42.5, b: true, f: false }],
      'test.csv',
      [
        { key: 'n', label: 'N' },
        { key: 'b', label: 'B' },
        { key: 'f', label: 'F' },
      ],
    );
    const text = await captureCsvText();
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines[1]).toBe('42.5,true,false');
  });

  it('leaves date strings unchanged', async () => {
    downloadRowsAsCsv([{ date: '2026-07-01' }], 'test.csv', [
      { key: 'date', label: 'Tarih' },
    ]);
    const text = await captureCsvText();
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines[1]).toBe('2026-07-01');
  });

  // ── Empty rows ───────────────────────────────────────────────────────

  it('downloads only the header row when rows is empty and columns are given', async () => {
    downloadRowsAsCsv([], 'test.csv', [
      { key: 'a', label: 'A' },
      { key: 'b', label: 'B' },
    ]);
    const text = await captureCsvText();
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines).toEqual(['A,B']);
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1);
  });

  it('is a safe no-op when rows is empty and no columns are given', () => {
    downloadRowsAsCsv([], 'test.csv');
    expect(createObjectURLSpy).not.toHaveBeenCalled();
    expect(clickSpy).not.toHaveBeenCalled();
  });

  // ── Column mapping ───────────────────────────────────────────────────

  it('only includes keys present in columns, in the given order', async () => {
    downloadRowsAsCsv(
      [{ z: 'last', a: 'first', m: 'mid' }],
      'test.csv',
      [
        { key: 'a', label: 'A' },
        { key: 'z', label: 'Z' },
      ],
    );
    const text = await captureCsvText();
    const lines = text.replace(/^﻿/, '').split('\r\n');
    expect(lines[0]).toBe('A,Z');
    expect(lines[1]).toBe('first,last');
  });

  it('sets the download filename on the anchor element', () => {
    downloadRowsAsCsv([{ a: 1 }], 'benchmark-2026-07-01.csv');
    expect(capturedAnchor).not.toBeNull();
    expect(capturedAnchor!.download).toBe('benchmark-2026-07-01.csv');
  });
});
