# AYAZ — Ürün Vizyonu

> Araç araştırması + strateji sentezi sonrası netleştirildi (2026-06-26).
> Detay: `03-strategy.md`. Hedef pazar: **önce Türkiye, sonra global.**

## Problem
Dijital pazarlama ekipleri işlerini 8-12 ayrı araçta (reklam panelleri, sosyal medya
planlayıcıları, e-posta, SEO, analitik, CRM) yürütüyor. Sonuç: dağınık veriler, sürekli
sekme değiştirme, tutarsız metrikler, her araç için ayrı abonelik maliyeti ve bütünsel
resmi görememe.

## Çözüm (Hipotez)
AYAZ, bu araçları **tek bir kokpitte** birleştirir:
- Tüm pazarlama verisini **tek doğruluk kaynağında** toplar (birleşik metrikler).
- Araçlar arası tek ekrandan **görüntüleme ve aksiyon** sağlar.
- Tek **abonelik** altında paketler.

## Neden kazanır? (Farklılaşma — doğrulanacak)
- Birleşik, tutarlı metrik katmanı (aynı sayı her yerde aynı anlama gelir).
- Hızlı "aha": kayıttan dakikalar sonra dağınık veri birleşmiş halde.
- Türkiye pazarına yerel uyum (KVKK, dil, yerel ödeme) — hedef pazara göre.

## Hedef Kitle (ICP)
- **Birincil:** Bir şirketin dijital pazarlamasını yöneten kişi (her sektör) —
  Google Ads + Meta + GA4 + (TikTok/LinkedIn/Search Console) gibi 5-10 ayrı panel
  arasında gidip gelen, kanal-üstü performansı tek yerde göremeyen pazarlama yöneticisi.
- **İkincil:** Dijital pazarlama ajansları (çok müşteri, white-label rapor ihtiyacı).

## Kazanma Kaması (Wedge)
"Tek panelde kanal-üstü performans + Türkçe otomatik içgörü" — **salt-okunur** başla
(reklam yazma yok → düşük risk, hızlı güven). Reklam yönetimi/optimizasyon sonraki faz.

## Strateji Kararları
- **Yap-vs-entegre:** Çekirdek (konektör + birleşik veri + dashboard + içgörü) sıfırdan
  bizim; LLM, döviz kuru ve ödeme dışarıdan entegre. (Detay: `04-architecture.md`)
- **Fiyat:** Sabit katmanlı abonelik (Funnel'in öngörülemez flexpoint modelinin tersi).

## Başarı Ölçütleri
- **Aktivasyon:** ilk kaynak bağlama oranı + time-to-value (hedef: 24 saatte ilk içgörü).
- **Tutundurma:** aylık aktif + bağlı kaynak sayısı; "eski panelleri açmayı bıraktı mı".
- **Gelir:** dönüşüm, ARPU, churn, expansion (kaynak/spend eşiği aşımı).

## Açık Sorular
- İlk hedef müşterilerin en çok hangi platformları kullandığı (konektör önceliklendirmesi).
- heyBooster public API kapsamı (entegre mi sıfırdan mı?).
