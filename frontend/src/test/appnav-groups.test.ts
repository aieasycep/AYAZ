/**
 * AppNav groups integrity test.
 *
 * Asserts that NAV_GROUPS covers every route in NAV_LINKS:
 *  (a) every NAV_LINKS href appears in exactly one group
 *  (b) every grouped href exists in NAV_LINKS
 *  (c) no duplicate hrefs across groups
 *  (d) group count === 7 and total grouped links === NAV_LINKS.length (34)
 */

import { describe, it, expect } from 'vitest';
import { NAV_LINKS, NAV_GROUPS } from '../components/AppNav';

describe('NAV_GROUPS integrity', () => {
  const flatNavHrefs = NAV_LINKS.map((l) => l.href);
  const groupedLinks = NAV_GROUPS.flatMap((g) => g.links);
  const groupedHrefs = groupedLinks.map((l) => l.href);

  it('(d) group count is 7', () => {
    expect(NAV_GROUPS).toHaveLength(7);
  });

  it('(d) total grouped links equals NAV_LINKS.length (34)', () => {
    expect(groupedLinks).toHaveLength(NAV_LINKS.length);
    expect(NAV_LINKS).toHaveLength(34);
  });

  it('(c) no duplicate hrefs across groups', () => {
    const seen = new Set<string>();
    const duplicates: string[] = [];
    for (const href of groupedHrefs) {
      if (seen.has(href)) duplicates.push(href);
      seen.add(href);
    }
    expect(duplicates).toEqual([]);
  });

  it('(b) every grouped href exists in NAV_LINKS', () => {
    const navSet = new Set(flatNavHrefs);
    const unknown = groupedHrefs.filter((h) => !navSet.has(h));
    expect(unknown).toEqual([]);
  });

  it('(a) every NAV_LINKS href appears in exactly one group', () => {
    const groupedSet = new Set(groupedHrefs);
    const missing = flatNavHrefs.filter((h) => !groupedSet.has(h));
    expect(missing).toEqual([]);
  });

  it('grouped hrefs set equals NAV_LINKS hrefs set (bidirectional)', () => {
    expect(new Set(groupedHrefs)).toEqual(new Set(flatNavHrefs));
  });
});
