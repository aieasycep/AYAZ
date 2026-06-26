# AYAZ — Ürün Stratejisi Brifingi

> Hazırlayan: Ürün Stratejisi ajanı · 2026-06-26 · Kapsam: TR-first → global "tek çatı" platform.
> Kaynak: 6 referans araç araştırması (`research/tools-inventory.md`).

## 1. Yetenek Haritası (Capability Map)

| # | AYAZ Modülü | Tek-cümle değer | Referans tool | Build/Integrate |
|---|---|---|---|---|
| M1 | **Bağlantılar (Connectors)** | Tüm platformlardan tek tıkla normalize veri çekme | Funnel.io | Integrate (OAuth), kaynak başına |
| M2 | **Birleşik Veri & Metrik Modeli** | Para/zaman/şema normalize tek "doğruluk kaynağı" | Funnel.io | **Build** (rekabetin kalbi) |
| M3 | **Birleşik Raporlama / Dashboard** | 10 sekme yerine tek panel, paylaşılabilir rapor | Looker Studio | **Build** (gömülü alt-küme) |
| M4 | **Otomatik İçgörü & Uyarı (AI)** | "Ne oldu, neden, ne yapmalı" + anomali alarmı | heyBooster | **Build** (ana farklılaşma) |
| M5 | **Reklam Yönetimi & Optimizasyon** | Kanal-üstü kampanya/bütçe optimizasyonu | Adin.ai | Build çekirdek + Integrate (yazma API) |
| M6 | **Feed / Pazaryeri** | Ürün feed + pazaryeri entegrasyonu, kural motoru | Channable | Integrate (pazaryeri) + Build (kural) |
| M7 | **Server-side Ölçümleme (CAPI)** | KVKK uyumlu first-party dönüşüm geçişi | SignalSight | **Build** (zor altyapı → sonraki faz) |

**Stack mantığı:** M1→M2 her şeyin temeli. Rakipler stack'in **bir katmanını** satıyor; AYAZ temeli bir kez kurup üzerine katman katman çıkıyor.

## 2. Örtüşme & Boşluk Analizi

**Parite alanı (herkes yapıyor, farklılaşma değil):** Konnektörler (hepsi Google/Meta/TikTok); çok-kanallı sipariş/stok senkronu (TR'de emtia); temel dashboard (Looker bedava).

**Pazardaki boşluk:**
| Boşluk | Kanıt | AYAZ fırsatı |
|---|---|---|
| Veri → İçgörü → Aksiyon tek akışta | Funnel "ne yap" demez; heyBooster reklam yönetmez; Adin pahalı/kapalı | M2+M4+M5 tek üründe |
| Şeffaf, öngörülebilir fiyat | Funnel flexpoint ($800-6000), Adin opak | Sabit, anlaşılır abonelik |
| SMB/orta segment | Adin Fortune-500, Funnel enterprise | KOBİ + ajans odağı |

**TR-spesifik boşluk (kazma noktası):**
| TR Gap | Durum | AYAZ hamlesi |
|---|---|---|
| Trendyol/Hepsiburada reklam+feed | Channable'da kesin yok; Trendyol reklam paneli ayrı silo | TR pazaryeri reklamını birleşik panele çek |
| Türkçe AI içgörü | Global araçlar İngilizce/genel | KVKK + Türkçe doğal-dil aksiyon önerileri |
| KVKK-uyumlu server-side | SignalSight altyapı, dashboard değil | Yerli rıza/eşleştirme |
| Yerel ödeme (iyzico) | Global SaaS ₺ tahsilatı zayıf | iyzico + ₺ faturalama |

## 3. ICP & Kazanma Kaması (Wedge)

**Birincil persona:** *Çok-kanallı TR e-ticaret markasının dijital pazarlama yöneticisi* — Trendyol/Hepsiburada + Google + Meta'da eşzamanlı satış, 3-8 kişilik ekip, aylık reklam ₺200K-2M, halen 5-10 panel arası gidip gelen kişi.

**KAMA (tek kazanan use-case):** **"Tek panelde kanal-üstü performans + Türkçe otomatik içgörü"** → M1+M2+M3+M4, **salt-okunur** (reklam yazma yok).

**Neden bu kama:**
- Reklam yönetimi (M5) ile başlamak riskli: yazma API'leri, müşteri parasıyla risk, "bozarsam zarar ettiririm" güven bariyeri. Önce *okuyarak* güven kazan.
- Feed/pazaryeri (M6) ile başlamak = emtia savaşı, düşük marj.
- İçgörü kaması düşük-riskli, yüksek "wow"; heyBooster modeli kanıtlanmış; Türkçe+Trendyol verisi rakipte yok.
- Bu kama M2 temelini kurar → sonraki modüller artımlı gelir.

## 4. MVP Kapsamı (in/out)

**IN (v1):** 6-8 konnektör (Google Ads, Meta, GA4, Search Console, **Trendyol**, **Hepsiburada**, TikTok) · birleşik metrik modeli (₺ normalize, harcama/ROAS/dönüşüm) · hazır kanal-üstü dashboard + paylaşılabilir/PDF rapor · **Türkçe otomatik içgörü + anomali alarmı** (e-posta/Slack/WhatsApp) · iyzico + ₺ faturalama + KVKK rıza temeli.

**OUT (ertelenmiş):** Reklam yazma/optimizasyon (Faz 2) · feed/pazaryeri yönetimi (Faz 2-3) · server-side/CAPI (Faz 3) · 500+ konnektör paritesi (sürekli) · BI warehouse export (enterprise) · mobil uygulama (Faz 2) · white-label (Faz 2).

**v1 başarı testi:** Kullanıcı tüm kanalları AYAZ'da görüp eski panelleri açmayı bırakıyor + en az 1 içgörüye göre aksiyon alıyor.

## 5. Abonelik & Fiyatlandırma

Sabit katmanlı abonelik (Funnel flexpoint'inin tam tersi = ana satış argümanı):

| Katman | Kime | İçerik | ₺/ay | $/ay |
|---|---|---|---|---|
| **Free** | Deneme | 1 kaynak, 1 dashboard, 7 gün veri, içgörü yok | 0 | 0 |
| **Starter** | Küçük marka | 3 kaynak, sınırsız dashboard, temel içgörü, e-posta uyarı, ≤₺150K spend | 1.490 | 39 |
| **Growth ⭐** | **ICP** | 8 kaynak (Trendyol/HB dahil), tam AI içgörü, anomali alarm, Slack/WhatsApp, ≤₺1M spend | 4.900 | 129 |
| **Agency** | Ajans | Çoklu hesap, white-label rapor, müşteri yönetimi, öncelikli destek | 12.900+ | 349+ |

**Çapa:** heyBooster ~$400 → Growth $129 daha geniş kapsamla; Funnel $800-6000 öngörülemez → "sürpriz fatura yok".
**Freemium:** Free katman = bağlantı kancası; 14 gün Growth tam-özellik trial; hedef time-to-value < 24 saat (bağlan → ilk içgörü). **Expansion:** kaynak/spend eşiği aşımı + Faz 2'de reklam yönetimi add-on. **Ajans/white-label:** yüksek-LTV ama Faz 2.

## 6. Konumlandırma

| Rakip | Sınırı | AYAZ konumu |
|---|---|---|
| Funnel.io | Veri taşır, "ne yap" demez; öngörülemez fiyat | "Veri + içgörü + aksiyon, sabit fiyat, tek çatı" |
| Looker Studio | Bedava ama sadece grafik | "Ne yapacağını söyleyen panel" |
| heyBooster | Reklam yönetmez, salt e-ticaret | "İçgörü + (yakında) aksiyon, TR pazaryeri dahil" |
| Adin.ai | Sadece kurumsal, pahalı, kapalı | "KOBİ/ajansın erişebileceği AI, şeffaf" |
| Channable | Trendyol/HB yok, sadece feed | "TR pazaryeri dahil, tüm pazarlama" |
| SignalSight | Altyapı, panel değil | "Ölçümleme dahil görünür tek kokpit" |

**Pitch:** *"AYAZ — tüm dijital pazarlama kanallarınızı (Trendyol ve Hepsiburada dahil) tek panelde birleştirir; size sadece veriyi değil, Türkçe olarak ne yapmanız gerektiğini söyler — 10 sekme yerine tek çatı."*

## 7. En Büyük 3 Risk
| Risk | Azaltma |
|---|---|
| Konnektör bakım yükü (API'ler değişir, "tek çatı" ilk kırılmada çöker) | İlk 8 kaynakla dar başla; contract testleri; konnektör sağlık izleme |
| AI içgörü "genel/işe yaramaz" algısı | TR-özel + kanal-üstü derinlik; insan-onaylı şablon kütüphanesi; "wow ilk içgörü" onboarding |
| Pazaryeri reklam API kıtlığı (Trendyol/HB yazma API'si sınırlı) | v1'i okuma kamasında tut; M5'te önce Google/Meta yazma; partner programına erken başvur |

## ⚠️ En önemli açık soru
**Trendyol & Hepsiburada'nın reklam/performans verisine programatik (okuma) erişim derinliği nedir?** v1 kamasının TR-pazaryeri farklılaşmasını ve Faz 2 reklam yol haritasını belirler. Entegrasyon ekibiyle + sahibin login'iyle **derhal** doğrulanmalı.
