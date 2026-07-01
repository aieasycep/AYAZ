import { describe, it, expect } from 'vitest';
import { buildAttentionHref } from '@/lib/command-center-focus';

// ---------------------------------------------------------------------------
// Insight → action bridge: Komuta Merkezi attention items link wherever the
// backend says (item.link). We only ever append ?focus=<campaign> when the
// link already points at /ads AND the title/detail names a specific
// campaign in a single-quoted segment. As of today the backend never emits
// an /ads-linked attention item (see backend/ayaz/services/command_center.py
// _build_attention — insights/inbox/content/goals/budget only), so this is
// currently a no-op safety net; these tests lock in that it stays inert
// until such an item exists, and behaves correctly if/when it does.
// ---------------------------------------------------------------------------

describe('buildAttentionHref', () => {
  it('passes through non-/ads links unchanged', () => {
    const item = {
      link: '/insights',
      title: '3 kritik uyarı',
      detail: "'Yaz Kampanyası' için ROAS düşük.",
    };
    expect(buildAttentionHref(item)).toBe('/insights');
  });

  it('appends ?focus=<campaign> for an /ads link with a quoted campaign mention', () => {
    const item = {
      link: '/ads',
      title: "'Yaz İndirimi' kampanyasında harcama sıçraması",
      detail: 'Son 3 günde harcama %40 arttı.',
    };
    expect(buildAttentionHref(item)).toBe('/ads?focus=Yaz%20%C4%B0ndirimi');
  });

  it('leaves /ads link unchanged when no quoted mention exists', () => {
    const item = {
      link: '/ads',
      title: 'Reklam performansı gözden geçirilmeli',
      detail: '2 reklam ROAS 1.0 altında.',
    };
    expect(buildAttentionHref(item)).toBe('/ads');
  });

  it('appends with & when the /ads link already has a query string', () => {
    const item = {
      link: '/ads?channel=meta',
      title: "'Kış Kampanyası' bütçeyi aştı",
      detail: '',
    };
    expect(buildAttentionHref(item)).toBe(
      `/ads?channel=meta&focus=${encodeURIComponent('Kış Kampanyası')}`,
    );
  });
});
