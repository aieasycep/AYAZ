/**
 * AppNav groups integrity test.
 *
 * Asserts that NAV_GROUPS (5 visible groups) + ACCOUNT_LINKS (account menu)
 * together cover every route in NAV_LINKS:
 *  (a) every NAV_LINKS href appears in exactly one group or in ACCOUNT_LINKS
 *  (b) every grouped href and every ACCOUNT_LINKS href exists in NAV_LINKS
 *  (c) no duplicate hrefs across groups or ACCOUNT_LINKS
 *  (d) NAV_GROUPS count === 5 and ACCOUNT_LINKS length === 4
 *      combined grouped links === NAV_LINKS.length (34)
 */

import { describe, it, expect } from 'vitest';
import { NAV_LINKS, NAV_GROUPS, ACCOUNT_LINKS } from '../components/AppNav';

describe('NAV_GROUPS integrity', () => {
  const flatNavHrefs = NAV_LINKS.map((l) => l.href);
  const groupedLinks = NAV_GROUPS.flatMap((g) => g.links);
  const groupedHrefs = groupedLinks.map((l) => l.href);
  const accountHrefs = ACCOUNT_LINKS.map((l) => l.href);
  // All reachable hrefs = nav groups + account menu combined
  const allGroupedHrefs = [...groupedHrefs, ...accountHrefs];

  it('(d) NAV_GROUPS count is 5', () => {
    expect(NAV_GROUPS).toHaveLength(5);
  });

  it('(d) ACCOUNT_LINKS count is 4', () => {
    expect(ACCOUNT_LINKS).toHaveLength(4);
  });

  it('(d) combined grouped links + account links equals NAV_LINKS.length (34)', () => {
    expect(allGroupedHrefs).toHaveLength(NAV_LINKS.length);
    expect(NAV_LINKS).toHaveLength(34);
  });

  it('(c) no duplicate hrefs across NAV_GROUPS and ACCOUNT_LINKS', () => {
    const seen = new Set<string>();
    const duplicates: string[] = [];
    for (const href of allGroupedHrefs) {
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

  it('(b) every ACCOUNT_LINKS href exists in NAV_LINKS', () => {
    const navSet = new Set(flatNavHrefs);
    const unknown = accountHrefs.filter((h) => !navSet.has(h));
    expect(unknown).toEqual([]);
  });

  it('(a) every NAV_LINKS href appears in exactly one nav group or in ACCOUNT_LINKS', () => {
    const allGroupedSet = new Set(allGroupedHrefs);
    const missing = flatNavHrefs.filter((h) => !allGroupedSet.has(h));
    expect(missing).toEqual([]);
  });

  it('combined hrefs set equals NAV_LINKS hrefs set (bidirectional)', () => {
    expect(new Set(allGroupedHrefs)).toEqual(new Set(flatNavHrefs));
  });
});
