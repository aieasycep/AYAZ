import { describe, it, expect } from 'vitest';
import { channelLabel, deltaIsGood, NEGATIVE_IS_GOOD } from '@/lib/channels';

describe('channelLabel', () => {
  it('bilinen slugları okunur etikete çevirir', () => {
    expect(channelLabel('google_ads')).toBe('Google Ads');
    expect(channelLabel('meta_ads')).toBe('Meta Ads');
    expect(channelLabel('tiktok_ads')).toBe('TikTok Ads');
    expect(channelLabel('sample')).toBe('Örnek Kaynak');
  });

  it('büyük/küçük harf duyarsızdır', () => {
    expect(channelLabel('GOOGLE_ADS')).toBe('Google Ads');
    expect(channelLabel('Meta_Ads')).toBe('Meta Ads');
  });

  it('bilinmeyen slugu olduğu gibi döndürür (ham anahtar değil ama en azından bozmaz)', () => {
    expect(channelLabel('bilinmeyen_kanal')).toBe('bilinmeyen_kanal');
  });

  it('boş/null/undefined için boş string döndürür', () => {
    expect(channelLabel(null)).toBe('');
    expect(channelLabel(undefined)).toBe('');
    expect(channelLabel('')).toBe('');
  });
});

describe('deltaIsGood', () => {
  it('normal (yüksek-iyi) metrikte artış iyi, düşüş kötü', () => {
    expect(deltaIsGood('roas', 5)).toBe(true);
    expect(deltaIsGood('conversions', 12.3)).toBe(true);
    expect(deltaIsGood('roas', -5)).toBe(false);
  });

  it('maliyet metriklerinde (NEGATIVE_IS_GOOD) artış KÖTÜ, düşüş iyi', () => {
    expect(deltaIsGood('spend', 35.7)).toBe(false);
    expect(deltaIsGood('cpc', 10)).toBe(false);
    expect(deltaIsGood('cpa', -8)).toBe(true);
    expect(deltaIsGood('cpm', -3)).toBe(true);
  });

  it('sıfır/null/undefined delta nötrdür (null döner)', () => {
    expect(deltaIsGood('spend', 0)).toBeNull();
    expect(deltaIsGood('roas', null)).toBeNull();
    expect(deltaIsGood('roas', undefined)).toBeNull();
  });

  it('NEGATIVE_IS_GOOD kümesi maliyet metriklerini içerir, performans metriklerini içermez', () => {
    expect(NEGATIVE_IS_GOOD.has('spend')).toBe(true);
    expect(NEGATIVE_IS_GOOD.has('cpc')).toBe(true);
    expect(NEGATIVE_IS_GOOD.has('cpa')).toBe(true);
    expect(NEGATIVE_IS_GOOD.has('cpm')).toBe(true);
    expect(NEGATIVE_IS_GOOD.has('roas')).toBe(false);
    expect(NEGATIVE_IS_GOOD.has('conversions')).toBe(false);
  });
});
