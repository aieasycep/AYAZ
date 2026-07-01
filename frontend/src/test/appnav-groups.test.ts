/**
 * AppNav groups integrity test.
 *
 * Asserts that NAV_GROUPS (10 sidebar sections) + ACCOUNT_LINKS (account/utility
 * area) together cover every route in NAV_LINKS:
 *  (a) every NAV_LINKS href appears in exactly one group or in ACCOUNT_LINKS
 *  (b) every grouped href and every ACCOUNT_LINKS href exists in NAV_LINKS
 *  (c) no duplicate hrefs across groups or ACCOUNT_LINKS
 *  (d) NAV_GROUPS count === 10 and ACCOUNT_LINKS length === 6
 *      combined grouped links === NAV_LINKS.length (35)
 */

import { describe, it, expect } from 'vitest';
import { NAV_LINKS, NAV_GROUPS, ACCOUNT_LINKS } from '../components/AppNav';

describe('NAV_GROUPS integrity', () => {
  const flatNavHrefs = NAV_LINKS.map((l) => l.href);
  const groupedLinks = NAV_GROUPS.flatMap((g) => g.links);
  const groupedHrefs = groupedLinks.map((l) => l.href);
  const accountHrefs = ACCOUNT_LINKS.map((l) => l.href);
  // All reachable hrefs = nav groups + account area combined
  const allGroupedHrefs = [...groupedHrefs, ...accountHrefs];

  it('(d) NAV_GROUPS count is 10', () => {
    expect(NAV_GROUPS).toHaveLength(10);
  });

  it('(d) ACCOUNT_LINKS count is 6', () => {
    expect(ACCOUNT_LINKS).toHaveLength(6);
  });

  it('(d) combined grouped links + account links equals NAV_LINKS.length (35)', () => {
    expect(allGroupedHrefs).toHaveLength(NAV_LINKS.length);
    expect(NAV_LINKS).toHaveLength(35);
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

  it('NAV_GROUPS uses the new function-based section labels', () => {
    const labels = NAV_GROUPS.map((g) => g.label);
    expect(labels).toContain('Genel Bakış');
    expect(labels).toContain('Sosyal Medya');
    expect(labels).toContain('Reklam');
    expect(labels).toContain('Kreatif');
    expect(labels).toContain('Analiz');
    expect(labels).toContain('SEO');
    expect(labels).toContain('Raporlar');
    expect(labels).toContain('Planlama');
    expect(labels).toContain('Veri & Entegrasyon');
    expect(labels).toContain('AI Asistanı');
  });

  it('SEO group contains /seo as its first link', () => {
    const seoGroup = NAV_GROUPS.find((g) => g.label === 'SEO');
    expect(seoGroup).toBeDefined();
    expect(seoGroup!.links[0].href).toBe('/seo');
    expect(seoGroup!.links[0].label).toBe('SEO Paneli');
  });

  it('/seo is present in NAV_LINKS', () => {
    const hrefs = NAV_LINKS.map((l) => l.href);
    expect(hrefs).toContain('/seo');
  });

  it('Veri & Entegrasyon group contains /integrations as first link', () => {
    const veriGroup = NAV_GROUPS.find((g) => g.label === 'Veri & Entegrasyon');
    expect(veriGroup).toBeDefined();
    expect(veriGroup!.links[0].href).toBe('/integrations');
    expect(veriGroup!.links[0].label).toBe('Entegrasyonlar');
  });
});
