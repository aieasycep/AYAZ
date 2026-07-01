# AYAZ — Rakip Panel Analizi: Funnel.io · Adin.ai · Channable

> **Bu dosya nedir?** AYAZ (TR-öncelikli, çok-kanallı dijital pazarlama kokpiti) için
> üç rakibin **giriş yapılmış canlı panellerinde** ekran ekran yapılan UX/IA araştırmasının
> tam dökümüdür. Başka bir Claude/sohbet session'ına yapıştırılıp bağlam olarak kullanılmak
> üzere kendi kendine yeter şekilde yazılmıştır.
>
> **Araştırma tarihi:** 2026-06-27
> **Yöntem:** Chrome (giriş yapılmış oturum) üzerinden her panel tek tek gezildi; ~50 ekran
> görüntüsü alındı, gerçek hesap verileri (EasyCep) gözlemlendi.
> **İncelenen hesaplar:** Funnel.io → workspace "EasyCep" · Adin.ai → platform.adin.ai (kullanıcı "Ayaz")
> · Channable → "EASYCEP BİLİŞİM A.Ş." (Company 89994, Project 256273).
>
> **Not (ekran görüntüleri):** Ham PNG'ler bu dosyaya gömülü değildir; her ekranın ne
> gösterdiği "Ekran Görüntüsü Dizini" bölümünde URL + ayrıntılı açıklamayla verilmiştir.
> Görselleri yeniden üretmek için ilgili URL'e giriş yapmış oturumla gidilebilir.

---

## 0) Nasıl kullanılır (başka session'a taşıma)

- Bu `.md` dosyasının **tamamını** yeni session'a yapıştırın ya da dosyayı projeye ekleyin.
- Yeni session'da örn. şöyle başlayabilirsiniz: *"Aşağıdaki rakip analizini bağlam al; AYAZ için
  X modülünün (ör. kural editörü / AI copilot / TR pazaryeri entegrasyonu) ürün gereksinim
  dokümanını ve ekran taslaklarını çıkar."*
- Hızlı referans için **§1 Karşılaştırma Tablosu** ve **§5 Beş Fırsat** bölümleri yeterlidir;
  derin tasarım için ilgili aracın "ekran ekran iş akışı" bölümüne inin.

---

## 1) Yönetici özeti + karşılaştırma tablosu

Üç araç **farklı katmanlarda** oynuyor ve hiçbiri tek başına AYAZ'ın "tek çatı" vaadini karşılamıyor:

- **Funnel.io** = pazarlama **veri hub'ı** (toplama → normalize → BI/warehouse/Sheets'e export). Güçlü yanı: veri normalizasyonu (Dimensions/Metrics kural motoru) + zamanlı export.
- **Adin.ai** = paid media **AI zekâ/optimizasyon** katmanı (skorlama + gerekçeli öneri + otomatik rapor). Güçlü yanı: "ne yap, ne kadar kazanırsın" diyen somut AI önerileri.
- **Channable** = **feed & marketplace** platformu (içe al → kuralla dönüştür → 380+ kanala yayınla + repricer/sipariş). Güçlü yanı: görsel IF/THEN/ELSE kural editörü + geniş kanal ağı.

| Boyut | Funnel.io | Adin.ai | Channable |
|---|---|---|---|
| **Ana iş** | Veri toplama + normalizasyon + export | AI skorlama + optimizasyon önerisi + raporlama | Feed dönüşümü + çok-kanal yayını + marketplace |
| **ICP** | Analitik ekipleri, ajanslar | Kurumsal/orta marka + performans ajansları | E-ticaret markaları + feed ajansları |
| **Veri kaynağı** | 500+ connector (reklam+analitik) | Reklam platformları (Meta/Google/TikTok) | Ürün feed'i (XML/CSV/API) |
| **Dönüşüm/kural** | Dimensions/Metrics kural motoru (connector+global, canlı önizleme) | — (AI öneriyor, kullanıcı uyguluyor) | Görsel IF/THEN/ELSE + Items before/after etki önizleme |
| **AI** | Funnel AI: **analiz** copilot (agentik, MCP/Skills/Docs) | "Ask your data" (kilitli) + **gerekçeli öneri** + AdWhisper ajan | Ask Charlie: **dokümantasyon/destek** botu + AI öznitelik zenginleştirme |
| **Skorlama / görüş** | Yok (ham veri) | **Var:** Effectiveness/Media(huni)/Creative skor | Yok (feed kalite uyarıları var) |
| **Çıktı / yayın** | Sheets, Excel, Looker Studio, BigQuery, S3, GCS, Azure | Excel export + raporlar | **Feed URL + 381 kanal** (comparison/marketplace/social) |
| **Server-side ölçüm** | **Activate** (CAPI, premium) | Yok | Yok |
| **Marketplace** | Yok | Yok | **Var:** Repricer + Orders + CSS Merchants |
| **TR sinyali** | TRY normalize (Funnel AI) | Müşteri: İş Bankası, Magnum, EasyCep | Kanallar: Akakçe, Kiralarsın (custom XML) |
| **Fiyat modeli** | **Flexpoints** tüketim kotası, satış-odaklı yükseltme | **Demo/satış-odaklı**, özellik kilitleme | **Self-serve modüler** (Core+Creatives+CSS+…) |
| **Açık fiyat?** | Kısmen (FP kullanımı görünür) | Hayır | **Evet** (€89+€30+€29 = €119/ay) |

---

## 2) Funnel.io — tam dosya

### 2.1 Ne yapar / kime (ICP)
Çok-kanallı pazarlama verisini tek yerde toplayan, **normalize eden** ve istenen hedefe
(Sheets/Excel/Looker Studio/warehouse) **zamanlanmış** akıtan bir "marketing data hub".
Hedef: orta-büyük pazarlama/analitik ekipleri ve ajanslar.
Hesap durumu: EasyCep workspace — 4 connector, 13 data source, 0 dashboard, 3 destination.

### 2.2 Menü / IA (ağaç)
```
Home  (workspace özeti, Data Source Health, Funnel AI kutusu, Quick Actions)
Data
 ├─ ANALYZE:  Data Explorer
 ├─ CONNECT:  Data sources (⚠) · Auto connects · Data requests
 └─ ORGANIZE: Dimensions · Metrics · Currencies
Plan
 ├─ Conventions (isimlendirme yönetişimi)
 └─ Budgets
Report
 ├─ Dashboards
 └─ Portals (dış paylaşım)
Measure   (MMM + attribution — Premium, satış görüşmesi)
Activate  (reklam platformlarına server-side dönüşüm sinyali / CAPI)
Export    (destinations / aktarım hedefleri)
Funnel AI
 ├─ New chat · Chat history · MCP
 └─ CONTEXT: Instructions · Skills · Documents
Subscription → Subscription overview · Flexpoints usage
```

### 2.3 Çekirdek iş akışı (ekran ekran ham gözlem)
1. **Data sources (liste):** 13 kaynak platform-hesabına göre gruplu. Sütunlar: Connector,
   Data Source Name, **Status** (OK / No Access / Paused), **Configuration Summary** (çekilen alanlar).
   Gerçek veriler: Google Analytics "easycep-app" (OK, GA4), TikTok "Cereyan//Easycep" (No Access),
   TikTok "Ecomm_Tiktok" (OK), Facebook Ads "TR_CreditCard_EasyCep" (Paused). Araç çubuğu:
   Groups, Columns, Warnings only, Filters, Search. Buton: **+ Connect data source**.
2. **Connect katalog:** Arama + "Popular" (Google Ads, Amazon Ads, Apple Search Ads, Microsoft
   Advertising, FB Ads/Pages, GA, GMB) + kategorili liste. UX detayı banner: *"Kimlik bilgin yoksa
   bir meslektaşı davet et — Invite a colleague."*
3. **Dimensions (normalizasyon):** Sekmeler **Custom (8) / Imported (249) / Built in (23)**.
   Özel boyutlar: Campaign ("GA + reklam platformlarındaki kampanyaları birleştirir"), Campaign Type,
   Media type ("Direct/Search/Affiliate/Social'a ayır"), Paid/Organic, Source_data, Traffic source,
   utm_medium, utm_source. (Sayfada in-app yardım widget'ı "Veronica from Funnel" çıkıyor.)
4. **Boyut detayı (Campaign):** Tip "Custom / STRING". **Standard rules** — her connector için map:
   Google Ads `Campaign` → ; Facebook `Campaign Name` → ; GA4 `Session campaign`/`Campaign GA4`/`Campaign UA` →
   hepsi "truncate to max 500 chars". Sağ panel **Funnel usage** (lineage): Field used in (1),
   Field depends on (7), Dashboards (0), Exports (3), Activate (0), Views (1), Budgets (0),
   "Show in Data Explorer". Created by Funnel, 3 Jul 2023.
5. **Kural editörü (Edit):** Sol form: Name/Description/Unit(STRING "Any text with full unicode support").
   **"Rules for specific Connectors"** (+Connector — her connector farklı işle, "Read more").
   **"Rules for all data"** (+Rule with condition; "kurallar sırayla, ilk eşleşen değer alınır").
   **Sağda CANLI ÖNİZLEME:** gerçek CAMPAIGN değerleri + ROW COUNT — (direct) 17, (not set) 16,
   (organic) 13, (referral) 21, Ecomm-Pmax-Tr-Google-MobilePhone 3, (ai-assistant) 5, vb.
   Toggle'lar: "Yesterday" tarih, "Show dependencies", "Show special characters".
   Eksik kuralda anında: *"Warning — There is an error in your rules. Fix it to preview data."*
   (Kuralı **kaydetmeden** Cancel ile çıkıldı; yapılandırma değiştirilmedi.)
6. **Data Explorer:** All Data Sources + Choose fields (7) + "Last month" + Add filter + Original
   currency; "Processed 3917 rows in 0.4s" + Load data; uyarı *"Metrics might be counted multiple
   times"*; Choose chart; sonuç tablosu (Currency/Data Source/Traffic source). Views + Export.
7. **Export (Exports listesi):** Sekme "Google Sheets (8)". Sütunlar: Name, **Schedule** (Daily at
   8:25 am), Status (✓), Last Run At (27 Jun, 8:25 am), Actions (aç/kapa toggle + şimşek "şimdi
   çalıştır" + edit + …). Örn export'lar: "Easycep - Digital Marketing - Main Report / Google-Tiktok-Yandex",
   "EasyKar". Butonlar: Copy from Workspace · Create Export.
8. **Create Export (hedef katalog):**
   - *Mevcut planda:* Google Sheets · Microsoft Excel · Data Studio (Looker Studio şablonları).
   - *"Available for trial" (üst pakete kilitli, premium ikonlu):* Amazon S3 · **Google BigQuery** ·
     Google Cloud Storage · Microsoft Azure Blob Storage.
9. **Report → Dashboards:** Boş durum ("Visualize your data… Build dashboards… explore template
   gallery"). Alt menü: Dashboards · **Portals**. Collaboration banner: "Invite a colleague".
10. **Template Gallery:** Kategoriler (Cross-channel, Paid Media). Şablonlar: "Performance Marketing
    overview", "E-commerce Performance Marketing", "Paid Ads overview" — her kart kullandığı
    connector logolarını gösterir (GA, FB, Google, LinkedIn, Microsoft, TikTok). Grid/list + arama.
11. **Funnel AI (copilot):** Sol: New chat · Chat history · **MCP**. CONTEXT: **Instructions ·
    Skills · Documents**. Girdi: *"@ for context, / for skills, or type your question"* + **mikrofon
    (sesli giriş)**. Hazır promptlar. **Çalıştırılan sorgu:** "Show total spend, clicks, conversions
    by channel (30d)". Davranış: sohbet başlığını otomatik üretti ("Multi-Channel Performance Last
    30 Days") → "Thought for a few seconds" → **analiz bağlamı oluşturdu** ("Created Channel
    Performance — 40 fields") → "Thought for 1s" → "I'll use Cost (spend), Clicks, Purchases by
    Traffic source" → grafik kartı üretti. **Sonuç tablosu (TRY'ye normalize):**
    Traffic source | Cost | Clicks | Purchases — All ₺242.975,11 / 96.708 / 0; Facebook ₺242.975,11 /
    96.708 / – ; TikTok ₺0,00 / 0 / 0; Google – / 0 / – . (TikTok/Google boş → uyarı ikonu.)
    Aksiyonlar: **"Open in Data Explorer"**, **"Save chart"**.
12. **Plan → Conventions:** *"Stick to your structure — kuralını söyle, ne kadar uyduğunu söyleyelim,
    anomalileri işaretleyelim ve istersen veriyi otomatik boyutlara bölelim."* + New convention.
    İllüstrasyon: kanal başına **adherence** + isimlendirme şablonunu boyutlara parçalama.
13. **Measure (Premium):** *"Measure what actually drives performance"* — ROAS **MMM (Marketing Mix
    Modeling)** + "Funnel Digital MMM" + Platform attribution. Self-serve değil → **"Book a meeting"**.
    Planlar: Digital / Advanced Measurement.
14. **Activate:** *"Send smarter conversion signals to ad platforms — temiz, gizlilik-güvenli veriyle
    geri besleme döngüsünü onar → daha çok atfedilen dönüşüm, daha düşük edinme maliyeti."* (CAPI).
15. **Flexpoints Usage (fiyat):** **395 / 400 FP (%99 dolu).** Connectors 200 FP (4), Destinations
    150 FP (1), Data Sources 45 FP (9), Total 395. Per-resource tablo (ör. Google Ads = Connector
    50 FP + Data Sources 15 FP = 65 FP). "Download as CSV". Yükseltme: **"Book a meeting / Contact sales"**.

### 2.4 Ayrıştırıcı özellikler
- Olgun **Dimensions/Metrics normalizasyon motoru** (connector+global kural, lineage, canlı önizleme).
- **Conventions** (isimlendirme uyum/adherence + otomatik boyuta parçalama).
- **Activate (CAPI)** + **Measure (MMM/attribution)**.
- **Funnel AI**: agentik, MCP sunucusu olma, Skills/Instructions/Documents (RAG), sesli giriş.

### 2.5 Mutlu eden UX detayları
- Kural editöründe **gerçek veri + row count canlı önizleme** ve anlık doğrulama uyarısı.
- Her alanda **"Funnel usage" bağımlılık/lineage paneli**.
- "Show special characters" (bozuk/görünmez karakter avı).
- "Invite a colleague" ve "Data requests" mikro-akışları.
- Data Explorer'da işlem süresi + satır sayısı şeffaflığı.

### 2.6 Zayıf / kafa karıştıran
- Dik öğrenme eğrisi (Dimensions/Metrics/Rules ayrımı soyut).
- Değerli hedefler (BigQuery/S3/warehouse) + Measure **üst pakete/satışa kilitli**.
- **FP %99 dolu** ama tek çıkış satış görüşmesi → sürtünme.
- Feed/pazaryeri/PPC kampanya kurgusu **yok** (salt veri hub'ı).
- TR para/KDV/kur "normalize edilen bir alan"; TR-öncelikli değil.

### 2.7 AYAZ için fikir tohumları
1. Dimensions kural editörünü (connector+global, sıralı) **canlı önizleme + row count + anlık doğrulama** ile çekirdek normalizasyon motoru yap.
2. Her alan/metrik için **bağımlılık-lineage paneli**.
3. **Naming convention adherence** + otomatik boyuta parçalama (TR ajans için).
4. **Zamanlanmış export** (Sheets/Looker/BigQuery) + aç-kapa + şimdi-çalıştır + son-durum.
5. AI copilot akışı: *bağlam oluştur → metrik/boyut seç → grafik üret → kaydet/explorer'da aç*; **TRY varsayılan**.
6. **MCP/Skills/Instructions/Documents** mimarisi (AYAZ AI'yı dışa MCP olarak aç).
7. Connector katalogunda "meslektaş davet et" + "kaynak talep et".

### 2.8 Fiyat notu
**Flexpoints (tüketim kotası).** 395/400 FP kullanımda. Her connector/kaynak/hedef FP yer.
Yükseltme satış-odaklı ("Contact sales"). Plan adı "EasyCep".

---

## 3) Adin.ai — tam dosya

### 3.1 Ne yapar / kime (ICP)
Paid media verisini **AI ile skorlayan, optimize öneren, otomatik raporlayan** "AI marketing
infrastructure". Slogan: *"AI Infrastructure for Enterprise Marketing — getiri 5x, zaman/maliyet 100x."*
Hedef: kurumsal/orta marka + performans ajansları. **TR kökü güçlü:** müşteriler **İş Bankası,
Magnum, EasyCep** + global **Under Armour, Bayer, Ajinomoto, Pluxee, Hyperoptic**.
Panel: `platform.adin.ai`, kullanıcı "Ayaz".

### 3.2 Menü / IA (ağaç)
```
Home  ("Ask your data" çubuğu, Products ızgarası, Product Updates/roadmap, Notifications(yakında))
Campaign → Overview  (skor + metrik + kampanya tablosu)
Media Intelligence → Smart Optimization → [AI Suggestions | AI Budget Optimizer]
Creative Intelligence  (kreatif skor/analiz)
Smart Reporting  (AI rapor galerisi)
Campaign Manager → Media Planner
Creative Hub  (Creative Upload)
Skills
Ask your data  (konuşma-AI — hesapta KİLİTLİ)

Products (ürünleştirilmiş AI çözümleri):
  AI Budget Optimizer · All Funnel Report · Awareness Report · Campaign Performance Report ·
  Comparison Report · CPAS Full Funnel · Creative Hub · Creative Report · Daily Report ·
  Daivid · Media Planner · Operational Report · Performance Planner · Reach Planner ·
  See Pages · Smart Optimization
```

### 3.3 Çekirdek iş akışı (ekran ekran ham gözlem)
1. **Home:** "Hi, Ayaz! Ready to co-create some success stories?" + büyük **"Ask your data"** çubuğu +
   Products ızgarası (Favorites/All) + sağda **Product Updates**:
   - *AdWhisper* (New, 2026-03-03): "AI Reporting Agent — uçtan uca raporlama, yapılandırma + içgörü,
     elle iş yok, kurumsal güvenlik."
   - *Campaign Update Module* (Upcoming, 2026-04-27): "Tek ekrandan Google/Meta/TikTok bütçe & durum."
   - *Custom Notification System* (Upcoming, 2026-05-11): "Kuralını koy, gerçek zamanlı uyarı + öneri."
2. **Campaign → Overview:** Filtreler (EasyCep / All Sources / 06.02–07.05.2026). **Skorlama:**
   Overall Effectiveness **55** (gauge), **Media Score 54** (Awareness 64 / Consideration 54 /
   Conversion 57), **Creative Score 53**. Total Budget ₺2.316.731. Active Campaigns 0 (hepsi paused).
   Performance Metrics: Cost ₺2.3M, Impressions 18.9M, Clicks 810K, CTR %4.29 (+ Manage Metrics).
   **Trend Analysis:** çoklu-metrik zaman serisi (Mar–May), sağda seçilebilir kartlar (Cost / Impressions
   / CPM ₺123 / CTR). **Campaign Performance tablosu:** Campaign Name / Delivery Status / Source /
   Channel Type / Cost / Impressions — renkli durum noktaları; örn: "Ecomm-Conv-Purchase-Statik"
   (PAUSED, META, OUTCOME_SALES, 66.341 / 595.187), "Ecomm-Pmax-Tr-Google-MobilePhone" (PAUSED,
   GOOGLEADS, PERFORMANCE_MAX, 840.871 / 6.202.754). **Export As Excel** + Manage Metrics. Üstte Meta
   aksiyon kırılımları (actions_link_click 65.9K, actions_omni_view_content 42.7K).
3. **Smart Optimization → AI Suggestions:** Tabs (AI Suggestions / AI Budget Optimizer), alt-tab
   (Overview / Campaign), Settings, filtreler, **"Reactions"** filtresi, sayfalama (2 sayfa).
   **Öneri kartı yapısı:** platform rozeti (Meta) + kampanya + tarih → **başlık (aksiyon)** →
   **Analysis:** (gerçek metrikli teşhis) → **Performance:** (beklenen % etki) → aksiyonlar
   **👍 / 👎 / "Mark as Applied" / ⓘ**. Gerçek örnekler:
   - "Add placement exclusions for Audience Network and remove Instagram Stories placement" —
     *Analysis:* CTR %72.5 düşük kaliteli yerleşimlerden şişkin, purchase rate %34 düşüyor —
     *Performance:* dönüşüm kalitesi +%40-50, edinme maliyeti −%20-30.
   - "Replace static images with carousel format showcasing product variety and pricing" —
     *Analysis:* statik 'HighCRO'dan 68 satın almanın yalnız 1'i → kreatif fatigue.
   - "Reduce frequency cap below 5 exposures per user to combat severe audience fatigue" —
     *Analysis:* Frequency 39.66, dönüşüm düşüyor.
   - "Reduce audience frequency from 61.5 by expanding retargeting to past-30-day video viewers…"
   - "Limit targeting to last 90 days instead of 180 days… CPP 55.674 çok yüksek…"
4. **Smart Optimization → AI Budget Optimizer:** Hesap (EasyCep) + kampanya seti (easycep_temmuz) +
   **Apply** → **"Magic Matrix"** (bütçe yeniden-dağıtım önizlemesi). Seçilen sette veri yok →
   *"Almost There! Adjust Filters — no data available for your current selection."* (Apply zararsız
   görüntüleme aksiyonu; canlı bütçeye dokunmuyor.)
5. **Smart Reporting:** "Everything You Need to See, All in One Place" — görsel kartlı rapor galerisi
   (All Funnel / Awareness / Campaign Performance / Comparison Report … her kartta "View Report").
   **Campaign Performance Report** → Brand/Campaign/tarih (Ecomm-Conv-Purchase-Statik, 24.02–24.03.2026)
   → **Apply** → otomatik rapor: meta veri (Budget 0, Cost 66.3K, Days 3965, Goal: Conversion,
   Buying Type: CPM) + renkli metrik kartları (Impressions 595K, Transactions 0, Clicks 21.3K,
   Installs 0) + **Cost vs Impressions** çift-eksen zaman serisi + **CPA/Transaction** grafiği (No Data).
6. **Creative Intelligence:** Kreatif skor/analiz (seçilen kampanya/tarihte veri yok → "Adjust Filters").
7. **Ask your data (kilitli):** Tıklayınca modal — **"🔒 Access Restricted — This feature is not
   enabled for your account. Contact the Adin.ai team to enable it."** (premium/upsell).

### 3.4 Ayrıştırıcı özellikler
- **Skorlama (0-100):** Effectiveness + huni-aşamalı Media + Creative — "görüş/teşhis" katmanı.
- **Rakamla konuşan kampanyaya özel AI önerileri** + **Mark as Applied + 👍/👎** geri-bildirim döngüsü.
- **AI Budget Optimizer "Magic Matrix".**
- **Ürünleştirilmiş AI ajanları** (AdWhisper) + panel-içi **yol haritası** şeffaflığı.

### 3.5 Mutlu eden UX detayları
- Önerilerin somutluğu (kampanya + gerçek metrik + beklenen % etki).
- "Mark as Applied + Reactions" ile öneri→aksiyon→geri-bildirim döngüsü.
- Motive edici dil; nazik/yönlendirici boş durumlar.
- Kampanya tablosunda tek-tık Excel export.

### 3.6 Zayıf / kafa karıştıran
- **"Ask your data" kilitli** (Access Restricted) — değerli özellik upsell duvarı arkasında.
- Çok sayıda "Product" + bazıları boş/veri-yok → ne zaman hangisi belirsiz.
- Açık fiyat yok (demo/satış-odaklı).
- Feed/pazaryeri/server-side ölçümleme **yok**.
- Öneriler İngilizce; TR-dilli üretim görünmüyor.

### 3.7 AYAZ için fikir tohumları
1. **Skorlama katmanı** (huni-aşamalı Effectiveness/Media/Creative).
2. **Gerekçeli AI öneri kartı** kalıbı (Başlık + Analysis + beklenen % etki) — TR-dilinde.
3. **Mark as Applied + 👍/👎 + Reactions** → kapalı geri-bildirim döngüsü + "uygulanan aksiyon" geçmişi.
4. **AI Budget Optimizer / yeniden-dağıtım matrisi.**
5. **Ürünleştirilmiş AI ajanları** + panel-içi yol haritası/Product Updates.
6. **Kural-tabanlı akıllı bildirim** (eşik/anomali → uyarı + öneri).
7. Her ekranda sabit **"Ask your data"** — ama AYAZ'da kilitsiz + TR-dilli.

### 3.8 Fiyat notu
Panelde açık fiyat **yok**; model **demo/satış-odaklı** ("Book a Demo") + **özellik kilitleme**
("Ask your data" / Creative Intelligence belirli hesaplara açık). Tek ticari sinyal: in-app roadmap.

---

## 4) Channable — tam dosya

### 4.1 Ne yapar / kime (ICP)
Ürün feed'ini içe alıp **kurallarla dönüştüren** ve 380+ kanala (comparison/marketplace/social/PPC)
yayınlayan + **marketplace sipariş/repricing** yöneten feed & marketplace platformu.
Hedef: e-ticaret markaları + feed ajansları.
Hesap: EASYCEP BİLİŞİM A.Ş. (Company 89994) / kullanıcı Yunus Emre / Project 256273 — 673 ürün, 6 kanal.

### 4.2 Menü / IA (ağaç)
```
Şirket düzeyi: Projects · CSS Merchants (Google CSS) · Plans & pricing · Company settings ·
               Ask Charlie (AI) · Help & Learn · Account
Proje düzeyi (256273):
  Dashboard  (sekmeler: Overview | Items | Analytics | Repricer | Orders)
  Setup      (alt: Import | Import rules | Import quality | Project fields | ID fields |
              Analytics | Order connections | Images)
  Optimize (AI Text)   (AI öznitelik zenginleştirme)
  Items
  Master rules         (global kurallar)
  Channels             (kanal başına boru hattı)
  Ask Charlie
Kanal boru hattı (her kanal): Settings › Categories › Rules › Mapping › Quality › Preview & export
```

### 4.3 Çekirdek iş akışı (ekran ekran ham gözlem)
1. **Projects (company):** Proje kartı "EASYCEP…" içinde feed/kanal sekmeleri: Google Shopping,
   Custom XML, **Akakçe** (TR fiyat karşılaştırma), Works. + Add new project ("bir mağaza/bir dil").
2. **Project Dashboard:** Total items **673**, Total channels **6**, Last update 20 dk. "Imported and
   exported items" grafiği + Detailed statistics. Üst sekmeler: Overview/Items/Analytics/**Repricer**/Orders.
3. **Setup → Import:** Kaynak bir **XML import** ("ec_tumurunler", rol **Main**). Her import:
   Settings / **Mapping** / Overview + Run now/Queued. "Combine imports". Import quality (1 uyarı).
4. **Field Mapping:** "Map your import fields to project fields" — kaynak XML'in **24 alanı** →
   Channable proje alanları. Her satırda **gerçek veri Preview** (cdn.easycep.com/assets/_web/img/
   product/2022/12…), tip seçici (liste/görsel/metin), Edit, **"Exclude from import"**.
5. **Channels (liste):** Create channel · Search · State · **Plan: "Core & Marketplace"**. Kanallar:
   **Akakçe** (custom XML), **Custom XML**, **Custom XML_Kiralarsın** (TR kiralama), **Google
   Shopping**, **Meta** … Her satırda boru hattı: **Settings › Categories › Rules › Mapping ›
   Quality › Preview** + Run now + durum.
6. **KURAL EDİTÖRÜ (Google Shopping → Rules):** "Setup your feed" adımları 1–6. Sol **kural listesi
   sırayla** (Set availability, Format text field (condition), Fill empty condition, Exclude out of
   stock, Discount price (percentage)…), kurallar **duraklatılabilir (pause)**. Sağda görsel
   **IF / THEN / ELSE:** *If `stock` is less or equal to [değer]* → **Then** take `availability`
   set to value **`out_of_stock`** → **Else** set to value **`in_stock`** → **+ Add section**.
   Altta **Items before / Items after** (kuralın kaç ürünü etkilediği önizleme) + **Calculate
   statistics**. Ayrı **Image rules** sekmesi. (Banner: "This rule is paused… Unpause rule".)
7. **Preview & export (kanal çıktısı):** Durum **🟢 Active "Your feed is ready to use!"** +
   Deactivate / Run now. **Export feed:** üretilen **feed URL'i**
   `https://files.channable.com/VLAvNHhl26ibyYOVYTZcHg==.xml` + **Copy feed link** / **Download feed**.
   "Connect your feed to Google" (Merchant Center). **XML Preview** gerçek çıktı:
   `<?xml version='1.0' encoding='utf-8'?> <rss xmlns:g="http://base.google.com/ns/1.0" …>
   <channel><title>Google Shopping</title><description>Google Shopping</description>…`
8. **Create channel (PPC/Marketplace katalog):** **381 kanal.** Kategoriler: **Comparison websites
   140 · Marketplaces 96 · Affiliates 38 · Social 11** + özel formatlar (CSV/XML/JSON, 10). Kartlarda
   **"AI setup available"** (Google Shopping, Meta). Pazaryerleri: Amazon, **Bol**, eBay / eBay Motors
   (Beta), **Otto Market**, Galaxus, Marktplaats Pro, Snapchat; **ChatGPT Commerce (OpenAI)** gibi
   yeni kanallar. Country + Category + Popularity filtreleri.
9. **Optimize (AI Text):** "AI enriched attributes — eksik öznitelikleri (renk vb.) mevcut import
   verisinden AI ile üret." Akış: hedef ürünler → aranacak proje alanları → **onayla/reddet/düzenle**
   → import'a uygula, tüm kanallarda kullan. İllüstrasyon: AI ürün listesine Color (Pink/Yellow/Blue/
   Marine) doldurup onay tiki koyuyor.
10. **Ask Charlie (AI):** Chat paneli — *"Hi Yunus! I'm Charlie, Channable's AI assistant 🤖 … Help
    Center içeriğiyle eğitildim. PPC / Insights / Creatives soruları için destek talebi açabilirim."*
    (Veri-sorgulayan değil; **dokümantasyon/destek botu** + ek/emoji/GIF/**sesli** giriş.)
11. **Plans & pricing (fiyat):** "All selected plans & add-ons":
    - **Core - Pro** [Core] — €89 × 1 = €89
    - **Creatives - Standard** [Creatives] — €30 × 1 = €30
    - **CSS - Standard** [CSS] — €29 × 0 = €0 (pasif)
    - **Toplam: €119/ay.** Cancel plan / Change subscription (self-serve).
    "Current active usage": **Package "Medium Business" (5.000 ürüne, 2 projeye, 6 kanala kadar,
    günde 24 senkron).** Active projects 1 / channels 6 / items 673. Rule versioning: Yes,
    Activity logs: Yes, Active Analytics: No, Active Insights: 1.

### 4.4 Ayrıştırıcı özellikler
- **Görsel IF/THEN/ELSE kural motoru** — sıralı kurallar, dal ekleme, **Items before/after etki
  önizleme**, **Rule versioning**, duraklatma.
- **381 kanallı yayın ağı** + **AI setup** ile otomatik kurulum.
- **Marketplace tam döngüsü:** feed + **Repricer** + **Orders** + CSS Merchants.
- **AI öznitelik zenginleştirme** (insan onaylı).
- Mapping'de gerçek veri önizleme + import quality.

### 4.5 Mutlu eden UX detayları
- Her kanalda numaralı **6 adımlı sihirbaz** (nereye gideceğin belli).
- Kural sonucunu **uygulamadan ürün sayısıyla görme** (Items before/after).
- Tek-tık **feed URL kopyala / indir / Run now** + canlı "Active" durumu.
- Kuralları **duraklatıp** üretimi etkilemeden düzenleme.
- Mapping'de görsel/satır önizleme ile yanlış-alan hatasını önleme.

### 4.6 Zayıf / kafa karıştıran
- **Ask Charlie sadece dokümantasyon botu** — veri sorgulayan/analiz eden AI yok.
- TR pazaryerleri (**Trendyol/Hepsiburada/N11/Çiçeksepeti**) **native değil** (custom XML/Akakçe ile dolaylı).
- Reklam analitiği/skorlama yok; "neyi neden" görüşü zayıf.
- Çok katmanlı kural yerleri (Import rules / Master rules / kanal Rules) dağınık gelebilir.
- Modüler fiyat toplam maliyeti öngörmeyi zorlaştırabilir.

### 4.7 AYAZ için fikir tohumları
1. **Görsel IF/THEN/ELSE kural editörü** + **"uygulamadan önce kaç ürünü etkiler" önizleme**.
2. **Kanal başına 6 adımlı sihirbaz** + **feed URL üretimi + "Connect to Google/Meta"**.
3. **TR pazaryerlerini birinci sınıf** (Trendyol/Hepsiburada/N11/Çiçeksepeti native feed+Repricer+Orders).
4. **AI öznitelik zenginleştirme** (eksik renk/materyal/GTIN'i başlıktan üret, insan onaylı).
5. **Rule versioning** (kural geçmişi/geri alma) + duraklatılabilir kurallar.
6. **Mapping'de gerçek veri önizleme** + import quality skoru.
7. **Modüler ama şeffaf fiyat** (paket + kullanım: ürün/proje/kanal/günlük senkron, canlı gösterge).

### 4.8 Fiyat notu
**Self-serve, modüler.** Core Pro €89 + Creatives Standard €30 + CSS Standard €29(€0/pasif) = **€119/ay.**
Paket "Medium Business" (5.000 ürün / 2 proje / 6 kanal / günde 24 senkron). Cancel/Change self-serve.

---

## 5) 3 araçta ortak olup TR pazarlamacının çok işine yarayacak ama çoğu üründe eksik 5 fırsat

1. **Tek döngüde TR-yerel pazaryeri + feed + reklam + sipariş.** Channable feed/pazaryeri yapıyor
   ama **Trendyol/Hepsiburada/N11/Çiçeksepeti native değil**; Funnel ve Adin feed/pazaryerine hiç
   girmiyor. AYAZ açığı: TR pazaryerlerini **birinci sınıf** (feed push + repricer + sipariş senkronu)
   **ve** aynı üründe reklam analitiği+optimizasyonla birleştirmek.

2. **TRY-öncelikli, KDV ve kur-farkı bilinçli finans/ROAS katmanı.** Üçünde de TRY *sonradan
   normalize edilen bir alan*. Hiçbiri **KDV dahil/hariç maliyet, döviz-dalgalanma düzeltmeli gerçek
   ROAS/CAC, enflasyon-düzeltmeli karşılaştırma** sunmuyor.

3. **Hem analiz eden hem AKSİYON uygulayan TR-dilli AI copilot (loop'u kapatan).** Funnel AI sadece
   analiz; Adin öneriyor + manuel "Mark as Applied"; Channable Charlie sadece dokümantasyon. Hiçbiri
   TR-dilinde "öneriyi platforma uygula → sonucu ölç → öğren" döngüsünü tam kapatmıyor.

4. **KVKK-uyumlu server-side ölçümleme + consent mode (kutudan çıkan).** Funnel'da var ama **Activate
   premium/global**; Adin ve Channable'da yok. TR e-ticaret için **KVKK + Consent Mode + CAPI** native,
   TR-mevzuatına göre yapılandırılmış olmalı.

5. **Çok-müşteri/çok-kanal isimlendirme + alan normalizasyonu yönetişimi (TR ajans gerçeğiyle).**
   Funnel'ın Dimensions+Conventions'ı güçlü ama feed/pazaryeri/AI ile bağlı değil; Adin/Channable'da
   yok. AYAZ **isimlendirme kuralı + uyum skoru + otomatik boyuta parçalama**yı tüm modüllere
   (analitik+feed+reklam) yayarak ayrışabilir.

---

## 6) Ekran Görüntüsü Dizini (her ekran: URL + ne gösteriyor)

> Görseller bu dosyaya gömülü değil; ilgili URL'e giriş yapmış oturumla gidilerek yeniden alınabilir.

**Funnel.io** (`app.funnel.io`)
- Home — `/#/account/-NZPfuQ2WHbZ4E01Cz88/home` — workspace özeti, Data Source Health, Funnel AI kutusu.
- Data Explorer — `/dataexplorer` — All Data Sources + Choose fields + filtre + sonuç tablosu.
- Data sources — `/datasources` — 13 kaynak, Status/Configuration Summary.
- Connect — `/datasources/connect/` — connector katalog (Popular + arama + "invite a colleague").
- Dimensions — `/fields/dimensions/` — Custom(8)/Imported(249)/Built in(23).
- Campaign boyutu — `/fields/dimensions/campaign` — Standard rules + Funnel usage(lineage).
- Campaign kural editörü — `/fields/dimensions/campaign/edit` — IF/rules + **canlı önizleme + row count**.
- Exports — `/destinations` — 8 Google Sheets export (schedule/status/last run/toggle).
- Create Export — `/destinations/new` — hedef katalog (Sheets/Excel/Looker + BigQuery/S3/GCS/Azure trial).
- Dashboards — `/dashboards` — boş durum + Template Gallery girişi.
- Template Gallery — `/dashboards/templates` — Cross-channel/Paid Media şablonları.
- Funnel AI — `/data-chat` — copilot girişi (MCP/Skills/Documents) + çalıştırılan sorgu sonucu (TRY tablo).
- Conventions — `/naming-conventions` — isimlendirme uyum/adherence.
- Measure — `/measurement-setup` — MMM/attribution (Premium, Book a meeting).
- Activate — `/activate` — server-side CAPI dönüşüm sinyali.
- Flexpoints Usage — `/subscription/fs1h4dav9db8vst/usage` — **395/400 FP** kırılımı.

**Adin.ai** (`platform.adin.ai`)
- Home — `/home` — Products ızgarası + Product Updates(roadmap).
- Campaign Overview — `/campaign/overview` — Effectiveness/Media/Creative skor + Trend + Campaign tablosu.
- Smart Optimization (AI Suggestions) — `/media-intelligence/smart-optimization/technical/overview` —
  gerekçeli öneri kartları (Analysis/Performance/Mark as Applied/👍👎).
- AI Budget Optimizer — `/media-intelligence/smart-optimization/ai-budget-optimizer` — Magic Matrix (no-data).
- Smart Reporting — `/smart-reporting` — rapor galerisi.
- Campaign Performance Report — `/smart-reporting/campaign-performance-report` — metrik kartları + grafikler.
- Creative Intelligence — `/creative-intelligence` — kreatif skor (no-data).
- Ask your data — (modal) — **Access Restricted (kilitli)**.

**Channable** (`app.channable.com`)
- Projects (company) — `/companies/89994` — proje + feed sekmeleri (Google Shopping/Custom XML/Akakçe).
- Project Dashboard — `/projects/256273/dashboard` — 673 ürün / 6 kanal / Overview-Items-Analytics-Repricer-Orders.
- Setup/Import — `/setup/imports` — XML import (Main) + Mapping/Settings/Overview.
- Field Mapping — `/setup/imports/630051/mapping` — 24 alan eşleme + gerçek veri preview + exclude.
- Channels — `/channels` — kanal listesi + boru hattı (Settings›…›Preview).
- Rules editörü — `/exports/470045/operators` — **IF/THEN/ELSE** + Items before/after + pause.
- Preview & export — `/exports/470045/preview` — **feed URL** + Connect to Google.
- XML Preview — `/exports/470045/preview/file_preview` — gerçek Google Shopping RSS/XML çıktısı.
- Create channel — `/channels/new` — **381 kanal** katalog (Comparison 140 / Marketplace 96 / Affiliate 38 / Social 11).
- Optimize (AI Text) — `/optimize` — AI öznitelik zenginleştirme.
- Ask Charlie — (panel) — dokümantasyon/destek AI botu.
- Plans & pricing — `/companies/89994/pricing` — **€119/ay** (Core €89 + Creatives €30 + CSS €0) / "Medium Business".

---

## 7) Bonus — AYAZ için birleşik backlog taslağı (rakip kanıtına dayalı)

| Modül | Kaynak ilham | Öncelik | Not |
|---|---|---|---|
| Veri normalizasyon motoru (IF/THEN, canlı önizleme) | Funnel Dimensions + Channable Rules | Yüksek | Çekirdek; TRY varsayılan |
| TR pazaryeri tam döngüsü (feed+repricer+sipariş) | Channable | Yüksek | Trendyol/HB/N11 native → güçlü diferansiyatör |
| Gerekçeli AI öneri + Mark as Applied | Adin AI Suggestions | Yüksek | TR-dilli + loop'u kapat |
| Skorlama katmanı (Effectiveness/Media/Creative) | Adin | Orta | Ham metriğin üstüne görüş |
| Zamanlanmış export (Sheets/Looker/BigQuery) | Funnel Export | Orta | Bağlılık yaratan basit özellik |
| Server-side ölçüm (KVKK + CAPI + consent) | Funnel Activate | Yüksek | TR-mevzuat farkı |
| Naming convention + adherence | Funnel Conventions | Orta | TR ajans kaosu çözücü |
| AI öznitelik zenginleştirme (insan onaylı) | Channable Optimize | Orta | Feed kalitesi |
| Kural-tabanlı akıllı bildirim | Adin (roadmap) | Orta | Eşik/anomali → uyarı+öneri |
| MCP/Skills/Documents AI mimarisi | Funnel AI | Düşük-Orta | Dış araç entegrasyonu |

---

*Hazırlayan: Claude (Claude Code) · Kaynak: 2026-06-27 canlı panel gezintisi (EasyCep hesapları).*
