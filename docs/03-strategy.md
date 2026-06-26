# AYAZ — Ürün Stratejisi Brifingi

> Hazırlayan: Ürün Stratejisi ajanı · 2026-06-26 (rev. ICP düzeltmesi) · Kapsam: TR-first → global "tek çatı" platform.
> Kaynak: 6 referans araç araştırması (`research/tools-inventory.md`).
> **ICP kararı:** Hedef = *genel dijital pazarlamacı* (her sektör; reklam + analitik + SEO + içgörü). Pazaryeri/feed satışı kapsam dışı.

## 1. Yetenek Haritası (Capability Map)

| # | AYAZ Modülü | Tek-cümle değer | Referans tool | Build/Integrate |
|---|---|---|---|---|
| M1 | **Bağlantılar (Connectors)** | Reklam/analitik platformlarından tek tıkla normalize veri çekme | Funnel.io | Integrate (OAuth), kaynak başına |
| M2 | **Birleşik Veri & Metrik Modeli** | Para/zaman/şema normalize tek "doğruluk kaynağı" | Funnel.io | **Build** (rekabetin kalbi) |
| M3 | **Birleşik Raporlama / Dashboard** | 10 sekme yerine tek panel, paylaşılabilir rapor | Looker Studio | **Build** (gömülü alt-küme) |
| M4 | **Otomatik İçgörü & Uyarı (AI)** | "Ne oldu, neden, ne yapmalı" + anomali alarmı | heyBooster | **Build** (ana farklılaşma) |
| M5 | **Reklam Yönetimi & Optimizasyon** | Kanal-üstü kampanya/bütçe optimizasyonu | Adin.ai | Build çekirdek + Integrate (yazma API) |
| M6 | **Server-side Ölçümleme (CAPI)** | KVKK uyumlu first-party dönüşüm geçişi | SignalSight | **Build** (zor altyapı → sonraki faz) |
| M7 | **Feed / Creative Otomasyonu** *(opsiyonel)* | Ürün feed'inden otomatik PPC + dinamik creative | Channable | Sonraki faz; e-ticaret odaklı, talebe bağlı |

**Stack mantığı:** M1→M2 her şeyin temeli. Rakipler stack'in **bir katmanını** satıyor; AYAZ temeli bir kez kurup üzerine katman katman çıkıyor. M7 (Channable'ın pazarlamaya bakan feed→PPC/creative yanı) yalnızca e-ticaret müşterisi talebi olursa ileri faz; **pazaryeri listeleme/satış kapsam dışı.**

## 2. Örtüşme & Boşluk Analizi

**Parite alanı (herkes yapıyor, farklılaşma değil):** Konnektörler (hepsi Google/Meta/TikTok); temel dashboard (Looker bedava); ham veri toplama.

**Pazardaki boşluk:**
| Boşluk | Kanıt | AYAZ fırsatı |
|---|---|---|
| Veri → İçgörü → Aksiyon tek akışta | Funnel "ne yap" demez; heyBooster reklam yönetmez; Adin pahalı/kapalı | M2+M4+M5 tek üründe |
| Şeffaf, öngörülebilir fiyat | Funnel flexpoint ($800-6000), Adin opak | Sabit, anlaşılır abonelik |
| SMB/orta segment | Adin Fortune-500, Funnel enterprise | KOBİ + ajans odağı |

**TR-spesifik avantaj (kazma noktası):**
| TR avantajı | Durum | AYAZ hamlesi |
|---|---|---|
| Türkçe AI içgörü | Global araçlar İngilizce/genel | KVKK + Türkçe doğal-dil aksiyon önerileri |
| KVKK-uyumlu veri & ölçümleme | Global araçlarda ikincil | Yerli rıza/veri ikametgahı |
| Yerel ödeme (iyzico) | Global SaaS ₺ tahsilatı zayıf | iyzico + ₺ faturalama, satın alma sürtünmesi yok |
| Yerel destek/Türkçe arayüz | Global araçlarda zayıf | Türkçe ürün + yerel destek |

## 3. ICP & Kazanma Kaması (Wedge)

**Birincil persona:** *Bir şirketin dijital pazarlamasını yöneten kişi / ajans* — Google Ads + Meta + GA4 + (TikTok/LinkedIn/Search Console) gibi 5-10 ayrı panel arasında gidip gelen, kanal-üstü performansı tek yerde göremeyen, aylık reklam bütçesi olan pazarlama yöneticisi. **Sektör bağımsız** (e-ticaret, hizmet, B2B fark etmez).

**KAMA (tek kazanan use-case):** **"Tek panelde kanal-üstü performans + Türkçe otomatik içgörü"** → M1+M2+M3+M4, **salt-okunur** (reklam yazma yok).

**Neden bu kama:**
- Reklam yönetimi (M5) ile başlamak riskli: yazma API'leri, müşteri parasıyla risk, "bozarsam zarar ettiririm" güven bariyeri. Önce *okuyarak* güven kazan.
- Salt dashboard (M3 tek başına) ile başlamak zayıf: Looker bedava → para vermezler. İçgörü (M4) değeri ekler.
- İçgörü kaması düşük-riskli, yüksek "wow"; heyBooster modeli kanıtlanmış; Türkçe içgörü + tek-çatı rakipte yok.
- Bu kama M2 temelini kurar → sonraki modüller (reklam yönetimi, CAPI) artımlı gelir.

## 4. MVP Kapsamı (in/out)

**IN (v1):** 5-7 konnektör — **Google Ads, Meta, GA4, Search Console, TikTok** (+ talebe göre LinkedIn/Microsoft) · birleşik metrik modeli (₺ normalize, harcama/ROAS/dönüşüm/CPA) · hazır kanal-üstü dashboard + paylaşılabilir/PDF rapor · **Türkçe otomatik içgörü + anomali alarmı** (e-posta/Slack) · iyzico + ₺ faturalama + KVKK rıza temeli.

**OUT (ertelenmiş):** Reklam yazma/optimizasyon (Faz 5) · server-side/CAPI (Faz 4) · feed/creative otomasyonu — Channable (opsiyonel, e-ticaret talebine bağlı) · 500+ konnektör paritesi (sürekli) · BI warehouse export (enterprise) · mobil uygulama (Faz 6) · white-label (Faz 3).

**v1 başarı testi:** Kullanıcı tüm kanalları AYAZ'da görüp eski panelleri açmayı bırakıyor + en az 1 içgörüye göre aksiyon alıyor.

## 5. Abonelik & Fiyatlandırma

Sabit katmanlı abonelik (Funnel flexpoint'inin tam tersi = ana satış argümanı):

| Katman | Kime | İçerik | ₺/ay | $/ay |
|---|---|---|---|---|
| **Free** | Deneme | 1 kaynak, 1 dashboard, 7 gün veri, içgörü yok | 0 | 0 |
| **Starter** | Küçük marka | 3 kaynak, sınırsız dashboard, temel içgörü, e-posta uyarı, ≤₺150K spend | 1.490 | 39 |
| **Growth ⭐** | **ICP** | 8 kaynak, tam AI içgörü, anomali alarm, Slack, ≤₺1M spend | 4.900 | 129 |
| **Agency** | Ajans | Çoklu hesap, white-label rapor, müşteri yönetimi, öncelikli destek | 12.900+ | 349+ |

**Çapa:** heyBooster ~$400 → Growth $129 daha geniş kapsamla; Funnel $800-6000 öngörülemez → "sürpriz fatura yok".
**Freemium:** Free katman = bağlantı kancası; 14 gün Growth tam-özellik trial; hedef time-to-value < 24 saat (bağlan → ilk içgörü). **Expansion:** kaynak/spend eşiği aşımı + Faz 5'te reklam yönetimi add-on. **Ajans/white-label:** yüksek-LTV ama Faz 3.

## 6. Konumlandırma

| Rakip | Sınırı | AYAZ konumu |
|---|---|---|
| Funnel.io | Veri taşır, "ne yap" demez; öngörülemez fiyat | "Veri + içgörü + aksiyon, sabit fiyat, tek çatı" |
| Looker Studio | Bedava ama sadece grafik | "Ne yapacağını söyleyen panel" |
| heyBooster | Reklam yönetmez, salt e-ticaret/İngilizce | "İçgörü + (yakında) aksiyon, Türkçe, sektör bağımsız" |
| Adin.ai | Sadece kurumsal, pahalı, kapalı | "KOBİ/ajansın erişebileceği AI, şeffaf" |
| SignalSight | Altyapı, panel değil | "Ölçümleme dahil görünür tek kokpit" |
| Channable | Feed/pazaryeri aracı, pazarlama kokpiti değil | "Tüm pazarlama tek panelde; feed ileride opsiyonel modül" |

**Pitch:** *"AYAZ — tüm dijital pazarlama kanallarınızı tek panelde birleştirir; size sadece veriyi değil, Türkçe olarak ne yapmanız gerektiğini söyler — 10 sekme yerine tek çatı."*

## 7. En Büyük 3 Risk
| Risk | Azaltma |
|---|---|
| Konnektör bakım yükü (API'ler değişir, "tek çatı" ilk kırılmada çöker) | İlk 5-7 kaynakla dar başla; contract testleri; konnektör sağlık izleme |
| AI içgörü "genel/işe yaramaz" algısı | Türkçe + kanal-üstü derinlik (rakibin göremediği birleşik resim); insan-onaylı şablon kütüphanesi; "wow ilk içgörü" onboarding |
| Bedava/ucuz alternatifler (Looker Studio, platform-içi paneller) salt-rapor değerini düşürür | Değeri salt grafik değil **otomatik içgörü + tek-çatı + Türkçe** üzerine kur; raporu değil aksiyonu sat |

## ⚠️ Açık soru
**İlk hedef müşterilerin en çok hangi panelleri/platformları kullandığı** — konektör önceliklendirmesini kesinleştirmek için (varsayım: Google Ads + Meta + GA4 ilk üç). Birkaç gerçek kullanıcıyla doğrulanmalı.
