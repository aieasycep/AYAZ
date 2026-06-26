# Birleştirilecek Araçlar — Envanter & Araştırma Bulguları

> Araştırma tarihi: 2026-06-26. Ekip (6 paralel araştırma ajanı) tarafından kamuya açık
> kaynaklardan derlendi. Bazı resmî siteler proxy politikası nedeniyle doğrudan
> çekilemedi; bulgular bağımsız üçüncü-taraf kaynaklarla çapraz doğrulandı. Giriş
> yapılarak (Chrome) doğrulanması gereken noktalar her profilde işaretlendi.

**Özet — araçlar bir "stack" oluşturuyor:**

| Araç | Katman | Sıfırdan zorluk (1-5) | Public API |
|------|--------|:---:|---|
| Funnel.io | Veri entegrasyonu / ELT (temel) | 5 | Zayıf (sadece file-import webhook) |
| Looker Studio | Raporlama / dashboard | 4 (alt-küme 2-3) | Sadece varlık/izin yönetimi |
| heyBooster | Otomatik içgörü / uyarı (AI) | 4 | Var (heybooster 3.0, kapsam belirsiz) |
| Adin.ai | Reklam yönetimi / optimizasyon | 5 | Yok (enterprise) |
| Channable | Feed / pazaryeri / PPC | 5 | Dar (sadece sipariş/stok senkron) |
| SignalSight | Server-side dönüşüm takibi (CAPI) | 4 | Event-ingest var; yönetim API'si belirsiz |

---

## 1. Funnel.io — https://funnel.io/
- **Tek cümle:** Pazarlama/reklam verisini 500-600+ konektörle toplayan, normalize eden (alan/para birimi/zaman dilimi), saklayan ve BI araçları + veri ambarlarına dağıtan bulut tabanlı pazarlama verisi merkezi (ELT).
- **Kategori:** Marketing data integration / ELT + raporlama. Rakipler: Supermetrics, Fivetran, Improvado, Adverity, Datorama.
- **Hedef kullanıcı:** Orta-büyük markaların pazarlama/analitik ekipleri, performans ajansları, RevOps/BI (fiyatı nedeniyle pratikte enterprise/scale-up).
- **Çekirdek özellikler:** 500-600+ hazır konektör; no-code normalizasyon (alan eşleme, para birimi/zaman dilimi dönüşümü, dedup, hesaplanan metrik); otomatik yenileme + kalıcı veri arşivi; Funnel Dashboards; çok sayıda export hedefi; "Activation" (Meta/Google Conversions API'ye dönüşüm geri gönderme); üst pakette MMM/attribution/incrementality.
- **Bağlandığı kaynaklar:** Google Ads, Meta, Microsoft, TikTok, LinkedIn, Amazon, Pinterest, Criteo, X Ads; GA4, Adobe Analytics; CRM/e-ticaret/affiliate (toplam 500-600+). **Export:** Looker Studio, Power BI, Tableau, Sheets, Excel, GA4; BigQuery, Snowflake, Redshift, Azure, S3, GCS, SFTP.
- **Fiyatlandırma:** Plan + "flexpoint" (kullanım kredisi). Konektör ~50, hesap ~5, viz hedefi ~150, ambar hedefi ~300 flexpoint. Pratik fatura $800–6.000+/ay, **öngörülemez** (G2/Reddit'te #1 şikayet).
- **API:** Zayıf. File-import webhook (token auth) net; veri-okuma REST API'si kısmen belirtiliyor ama kapsam/auth public değil. Resmî pozisyon "no-code connector" odaklı, geliştirici API'si değil.
- **Sıfırdan zorluk: 5** — Zorluk konektör sayısı (500-600) ve her birinin sürekli bakımı (farklı auth/rate-limit/şema/sık değişim) + şema normalizasyonu + ölçek. **AYAZ için:** tümünü yazmak gerçekçi değil; TR-öncelikli ilk fazda en kritik ~10-20 kaynağı sıfırdan yaz, long-tail kademeli.
- **Doğrulanacak (login):** Güncel kesin fiyatlar; veri-okuma API kapsamı/auth; konektör sayılarının paket dağılımı; tam export hedef listesi.

## 2. Looker Studio (Google Data Studio) — https://lookerstudio.google.com/
- **Tek cümle:** Google'ın ücretsiz, bulut tabanlı self-servis BI/dashboard aracı; veri kaynaklarına bağlanıp interaktif, paylaşılabilir, gömülebilir raporlar oluşturur.
- **Kategori:** BI / dashboard & raporlama, veri görselleştirme.
- **Çekirdek özellikler:** Sürükle-bırak rapor editörü; geniş görsel seti (tablo, pivot, scorecard, zaman serisi, grafik tipleri, harita, gauge); filtreler/tarih kontrolleri/drill-down; hesaplanmış alanlar; **veri harmanlama (blending, 5 tabloya kadar, 5 join)**; paylaşım; **zamanlanmış PDF e-posta**; iframe/embed.
- **Bağlandığı kaynaklar:** ~21 native (BigQuery, Sheets, GA4, Google Ads, Search Console, YouTube, SQL DB'leri, CSV) + ~800-1000 partner konektör (Supermetrics, Funnel, Windsor.ai…) + Apps Script community connector'lar.
- **Fiyatlandırma:** Ücretsiz çekirdek; **Looker Studio Pro ~$9/kullanıcı/ay** (gerçekte kullanıcı + Google Cloud projesi başına). 30 gün deneme.
- **API:** Community Connector framework (Apps Script: `getAuthType/getConfig/getSchema/getData`); Linking API (URL ile şablon rapor); embedding; REST API yalnızca **varlık/izin yönetimi** — programatik rapor OLUŞTURMA/okuma YOK.
- **Sıfırdan zorluk: 4** (tam klon) / **2-3** (AYAZ'ın ihtiyacı). **AYAZ için:** tam Looker klonu GEREKMEZ. Gereken alt-küme: kendi birleşik verimiz üzerinde önceden tanımlı + biraz özelleştirilebilir dashboard'lar, standart görsel seti, tarih/filtre, zamanlanmış PDF/e-posta, paylaşılabilir/gömülebilir müşteri raporları. Veri zaten tek şemada toplandığı için Looker'dan kolay.
- **Doğrulanacak:** Native konektör tam listesi; Pro fiyat nüansı; partner konektör sayısı.

## 3. heyBooster — https://www.heybooster.ai/tr  *(TR-origin, Tallinn)*
- **Tek cümle:** GA4/Google Ads/Meta/Search Console gibi kaynaklardan veriyi toplayıp ML + uzman-kuralı tabanlı motoruyla günlük otomatik içgörü, anomali uyarısı ve bütçe önerisi üreten; dashboard + e-posta + Slack'le ileten AI pazarlama analitiği platformu.
- **Kategori:** AI destekli pazarlama analitiği / otomatik içgörü & anomali tespiti (e-ticaret odaklı). **AYAZ'ın ana farklılaştırma alanı.**
- **Çekirdek özellikler:** SEO insights; **anomali/marketing alerts** (duraklatılmış kampanya, stok-tükendi+gösterim, ROAS/gelir düşüşü, ölçüm hatası) günlük e-posta/Slack; KPI/hedef takibi; executive reports; ROAS/funnel/ürün/creative içgörüleri; çapraz kanal bütçe optimizasyonu; PMax analizi.
- **Bağlandığı kaynaklar:** GA4, Google Ads, Search Console, Meta, Criteo, RTB House, Shopify (App Store'da app). Teslim: dashboard, e-posta, Slack.
- **Fiyatlandırma:** Zaman içinde değişmiş; güncel sinyaller: free-forever + ücretli ~$400/ay'dan (danışmanlık dahil). AppSumo lifetime $69 (kampanya).
- **API:** **Var** (heybooster 3.0 public API) — ama kapsam/doküman/auth public değil.
- **Nasıl çalışıyor (tahmin):** Günlük ETL → normalize ambar → iki katmanlı içgörü motoru: (1) uzman-kuralı/eşik + (2) zaman serisi anomali tespiti; çıktılar önceliklendirilip doğal-dil cümlelere (muhtemelen şablon + LLM) dönüştürülüp push ediliyor. Değer, kural kalibrasyonu ve yanlış-pozitif yönetiminde.
- **Sıfırdan zorluk: 4** — (a) veri-kaynağı entegrasyonları (AYAZ zaten kuracak, ortak iş), (b) içgörü/anomali algoritmaları + e-ticaret domain kuralları (asıl zorluk). NL özet katmanı LLM ile bugün kolay.
- **Doğrulanacak (login):** Güncel fiyat tablosu; tam entegrasyon listesi; Public API kapsamı; içgörü motorunun gerçekte LLM mi kural+istatistik mi; referans müşteri iddiaları.

## 4. Adin.ai — https://www.adin.ai/  *(TR-founded, İşbank destekli)*
- **Tek cümle:** Kurumsal reklamverenler için medya planlama, satın alma, gerçek-zamanlı optimizasyon ve raporlamayı tek AI-native panelde birleştiren çok-kanallı reklam yönetim platformu ("AI OS").
- **Kategori:** AI cross-channel reklam/medya yönetim + optimizasyon. Rakipler: Skai, Marin, Smartly, Pacvue, Improvado, Madgicx. (Kreatif ÜRETİCİ değil; creative effectiveness DAIVID ortaklığıyla.)
- **Hedef kullanıcı:** Enterprise/Fortune-500 (L'Oréal, Vodafone, Under Armour Europe, Bayer, İşbank). SMB değil.
- **Çekirdek özellikler:** AI Media Planner (sonuç projeksiyonu, bütçe dağıtımı); AI Media Optimizer (gerçek zamanlı); AI Targeting; Smart Reporting + cross-channel scoring + MMM; AI Forecasting; Creative Effectiveness (DAIVID).
- **Bağlandığı kaynaklar:** Google, Meta, TikTok, X + programmatic, Reserved Media, digital radio, DOOH, CTV; Adjust (MMP).
- **Fiyatlandırma:** Açık değil (enterprise "talk to sales"). Capterra rakamları çelişkili/düşük güven.
- **API:** Public API/doküman bulunamadı.
- **Sıfırdan zorluk: 5** — (1) çok sayıda reklam-platformu **yazma** API entegrasyonu, (2) cross-channel optimizasyon/bütçe dağıtım + MMM/forecasting (ekonometri + ML), (3) gerçek-zamanlı multi-tenant normalizasyon.
- **Doğrulanacak (login):** Gerçekten canlı bağlanan platformlar; optimizasyon otomatik mi öneri mi; public/partner API; gerçek fiyat; altta hangi modeller; TR pazarı desteği.

## 5. Channable — https://www.channable.com/
- **Tek cümle:** E-ticaret ürün feed'ini tek yerden kurallarla zenginleştirip 2.500-3.000+ kanala (Google Shopping, Meta, Amazon, bol, Zalando…) listeleyen, reklam üreten ve pazaryeri siparişlerini geri senkronize eden çok kanallı feed/pazaryeri platformu.
- **Kategori:** Product Feed Management + Marketplace Integrator + PPC otomasyonu. Rakipler: DataFeedWatch, Feedonomics, Productsup, Lengow, ChannelEngine.
- **Hedef kullanıcı:** E-ticaret perakendecileri/markaları + ajanslar (~12.000 marka, ~1.300 ajans iddiası).
- **Çekirdek özellikler:** Feed yönetimi (master feed + no-code if/then kural motoru); Marketplace Integrator (listeleme/stok/sipariş senkron); PPC otomasyonu (feed'den kampanya); Dynamic Image Editor (creatives); Insights (POAS/ROAS); Google CSS; AI attribute üretimi + 8 dil çeviri.
- **Bağlandığı kaynaklar:** Google Ads/Shopping/CSS/PMax, Microsoft, Meta, TikTok Shop, Pinterest, Snapchat; pazaryerleri Amazon/bol/Zalando/eBay/Allegro/AliExpress/Carrefour/Cdiscount (3.000+ kanal); e-ticaret Shopify/Magento/WooCommerce/Shopware/Lightspeed; ERP SAP/NetSuite/Dynamics.
- **Fiyatlandırma:** Modüler. Core ~$49-104/ay + eklentiler (Marketplaces ~$35, PPC ~$56-83, CSS ~$25). Konfigürasyona bağlı.
- **API:** **Var ama dar** — `api.channable.com/v1`, Bearer token. Sadece **Orders/Shipments/Cancellations/Returns/Offers-Stock** (sipariş döngüsü). Feed/kural/listeleme yönetimi API'de YOK (UI + CSV/XML/Sheets).
- **Sıfırdan zorluk: 5** — 2.500-3.000+ kanal/pazaryeri entegrasyonu ve sürekli bakımı; çift yönlü sipariş/stok/iade; reklam API'leri; performanslı kural motoru; milyonlarca SKU batch pipeline.
- **🔴 TR boşluğu:** Kamuya açık listede **Trendyol/Hepsiburada YOK** — AYAZ için kritik farklılaşma fırsatı (doğrulanacak).

## 6. SignalSight — https://www.signalsight.io/  *(ZZG Tech, Londra)*
- **Tek cümle:** Reklam platformlarına (Meta, TikTok, Google, Snapchat, Pinterest) web/app/CRM/offline kaynaklardan sunucu-taraflı (server-side) first-party dönüşüm sinyali gönderen ve lead'leri CRM'e akıtan "first-party data gateway / server-side tracking" platformu.
- **Kategori:** Server-side conversion tracking & first-party data gateway (CAPI). **Altyapı**, dashboard değil.
- **Çekirdek özellikler:** Web Conversions API; App CAPI (SDK'sız); Web2App/Web2Lead landing builder; MMP entegrasyonu (AppsFlyer, Adjust); Messaging Signals (WhatsApp/Messenger); Lead Sync (Zoho CRM); Offline Conversion Tracking; advanced matching/dedup/consent (KVKK/GDPR/CCPA vurgusu).
- **Bağlandığı kaynaklar:** Meta, TikTok (resmî entegrasyon), Google, Snapchat, Pinterest, Reddit, X; AppsFlyer/Adjust; Zoho + Custom API; WhatsApp/Messenger/Instagram; sGTM, Meta CAPI Gateway; FTP/offline.
- **Fiyatlandırma:** Freemium (500K event, 100 tracker, 500 connection); managed $999'dan.
- **API:** Event-ingest API + Custom API var; klasik geliştirici REST/SDK belirsiz (kurulum çoğunlukla no-code loader).
- **Sıfırdan zorluk: 4** — çok platformun server-side conversion API'lerine entegrasyon + identity matching/hashing + dedup + consent + yüksek-hacim event pipeline. **AYAZ için:** temel CAPI göndericileri yazılabilir; tam gateway+dedup+MMP+landing paketi pahalı → kısmen entegrasyon mantıklı olabilir.
- **Doğrulanacak (login):** Fiyat kademeleri; gerçek yönetim API'si var mı; desteklenen platform tam listesi; native CRM'ler; veri konumu/KVKK detayı.

---

## Sahibi tarafından login ile doğrulanacak öncelikli sorular
1. **Trendyol & Hepsiburada** reklam/performans verisine programatik (okuma) erişim derinliği — Partner API yeterli mi? *(v1 kamasının fizibilitesini belirler.)*
2. **heyBooster public API** kapsamı/doküman/auth — entegre mi sıfırdan mı kararı için.
3. **SignalSight & Channable** fiyat kademeleri ve gerçek yönetim API'lerinin varlığı.
4. **Adin.ai** optimizasyon otomatik mi öneri mi + TR desteği.
