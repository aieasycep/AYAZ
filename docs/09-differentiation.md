# AYAZ — Farklılaşma & Rekabet Hendeği Brifingi

> Hazırlayan: Ürün Stratejisi ajanı · 2026-06-26 · Kapsam: çekirdek platform (M1–M10) hazır.
> Girdi: `research/tools-inventory.md`, `03-strategy.md`, `05-comprehensive-roadmap.md`, `04-architecture.md` + canlı kod (`backend/ayaz/services/*`).
> Amaç: rakipleri **kesin biçimde** geçecek farklılaştırıcıları sıralamak ve sıradaki 3 derinleştirme dalgasını önermek.
> Karar özeti: **AYAZ AI Copilot = bayrak kama (#1).** Üzerine cross-channel bütçe optimizasyonu (#2) ve hedef/pacing (#3) eklenir.

---

## 1. Hendek (Moat) Tezi — "Tek çatı + Türkçe + AI aksiyon"

**Tez:** AYAZ'ın hendeği tek bir özellik değil; **birleşik veri katmanının (M2) üzerine dizilmiş 10 modülün bileşimi**. Rakiplerin her biri stack'in *tek bir katmanını* satıyor. Bir katman satıcısının AYAZ'a yetişmesi için kendi çekirdeğini bozup eksik 9 katmanı sıfırdan kurması gerekir — bu yapısal olarak pahalı ve yavaş.

### Neden tek-katman rakipler kopyalayamaz

| Rakip | Sahip olduğu tek katman | Kopyalamak için kurması gereken | Yapısal engel |
|---|---|---|---|
| **Funnel.io** | Veri ELT (M1+M2 ham) | İçgörü + aksiyon + reklam + feed + CAPI + Türkçe | İş modeli "veri taşıma" (flexpoint); "ne yap" demek konumlandırmaya aykırı. AI Data Chat'i var ama **veri-üstü sohbet**, aksiyon değil. |
| **Looker Studio** | Görselleştirme (M3) | Veri normalize + içgörü + her şey | Google'ın ürünü genel BI; pazarlama-özel aksiyon + Türkçe domain motoru stratejik öncelik değil. |
| **heyBooster** | İçgörü/anomali (M4) | Reklam yönetimi + feed + CAPI + workspace + tek-çatı | E-ticaret/İngilizce odaklı; reklam **yönetmiyor**, feed/CAPI yok. En yakın rakip ama dar. |
| **Adin.ai** | Reklam optimizasyon (M6) | KOBİ erişimi + şeffaf fiyat + self-serve + Türkçe self-serve | Enterprise/kapalı/"talk to sales" DNA'sı; KOBİ'ye inmek tüm GTM'ini bozar. |
| **Channable** | Feed/pazaryeri (M5) | Analitik + içgörü + reklam okuma + CAPI | Feed/pazaryeri odaklı; pazarlama kokpiti değil. |
| **SignalSight** | CAPI altyapısı (M7) | Dashboard + içgörü + her şey | "Altyapı, panel değil" — bilinçli olarak görünmez katman. |

### Üç katmanlı hendek (en derinden en yüzeye)

1. **Veri hendeği (M1+M2) — yavaş ama derin.** Birleşik fact + tek Metric Layer (`services/metrics.py`: CTR/CPC/CPA/ROAS tek tanım). Bu, sahip olunca kolay görünen ama her modülü besleyen "compound" varlık. Rakipte M2 olmadan üst katmanlar kanal-üstü olamaz.
2. **Aksiyon hendeği (M4+M6+M9) — "ne oldu" değil "ne yap".** 6 dedektör (`services/insights.py`) + Türkçe narrator + reklam önerisi (`services/ads.py`, dedektörleri kampanya granülünde yeniden kullanıyor) + kural motoru (`services/automation.py`). Funnel/Looker burada yapısal olarak duramaz.
3. **Yerellik + bileşim hendeği (Türkçe + KVKK + iyzico + tek-çatı) — taklit edilmesi en pahalı.** Global araç için Türkçe domain-kalibreli AI + KVKK veri ikametgâhı + ₺/iyzico tahsilat **ikincil**; bizim için **birincil**. Bileşim (10 modül tek veri üstünde) tek tek özellik kopyalamayla yakalanmaz.

**Bileşim çarpanı:** her yeni modül önceki modüllerin değerini artırır (M2 olmadan M4 sığ; M4+M6 olmadan Copilot sadece chatbot). Rakip "bir özellik" kopyalasa bile **bileşimi** kopyalayamaz — hendeğin asıl kaynağı bu.

**Aciliyet sinyali (2026 pazar):** Funnel "AI Data Chat", Coupler.io "AI agent + MCP" gibi rakipler sohbet katmanını bağlamaya başladı — ama hepsi **tek-katman (salt-veri) + İngilizce**. Aksiyona dokunan, kanal-üstü, Türkçe bir Copilot henüz yok. Pencere açık; geç kalırsak parite olur.

---

## 2. Farklılaştırıcılar — Sıralı (inşa önceliği)

Sıralama kriteri: **(değer × rakip-üstünlüğü × bileşim etkisi) / build-zorluğu**, çekirdeğin mevcut olmasıyla ağırlıklandırılmış. Build zorluğu 1 (kolay) – 5 (zor).

### #1 — AYAZ AI Copilot (sohbet eden, veriye gömülü, tool-use'lu, Türkçe)
- **Ne:** Birleşik veri üstünde Türkçe konuşan asistan. Soru sorar ("son 30 günde hangi kanal para kaybettiriyor?"), **gerçek veriden** yanıtlar, kaynak gösterir, ve mevcut modül fonksiyonlarını **tool olarak çağırır** (rapor kur, içgörü üret, kampanya öner, kural taslakla).
- **Kimi nasıl geçer:**
  - **Funnel.io / Looker:** Onlar grafik/veri verir, kullanıcı yorumlar. Copilot **yorumu ve sonraki adımı** verir; AI Data Chat'in salt-veri tablosuna karşı aksiyon-yönelimli + kanal-üstü.
  - **heyBooster:** İçgörüyü *push* eder (tek yön); Copilot **çift yönlü** — kullanıcı "neden?" diye kazabilir, "peki ne yapayım?" diye derinleşebilir. + Türkçe + sektör bağımsız.
  - **Adin.ai:** Enterprise panel; Copilot aynı zekâyı **doğal dille KOBİ'ye** açar (öğrenme eğrisi sıfır).
- **Kullanıcı değeri:** Öğrenme eğrisini sıfırlar; "10 sekme + uzman bilgisi" yerine "tek soru". Time-to-value'yu dakikalara indirir. Junior pazarlamacıyı kıdemli gibi çalıştırır.
- **Build zorluğu: 2.** Çekirdek **zaten var**: `ClaudeNarrator` (`services/narrator.py`) raw httpx ile Claude'a bağlı, JSON üretiyor, fallback'li. Her modülün servis fonksiyonu (metrics, insights, ads, reports, feeds) hâlihazırda tool olarak sarmalanmaya hazır tipli imzalara sahip. Gereken: tool-spec katmanı + sohbet oturumu/geçmiş + grounding/citation + read-only tool guardrail.
- **MVP dilimi:** Salt-okunur 5-6 tool (metrik sorgula, içgörü listele, kampanya performansı, kanal kıyas, rapor-özeti). Her yanıt **veri kaynağını alıntılar** ("Google Ads, 1-30 Haziran"). Aksiyon tool'ları (kural oluştur, rapor kur) v2.

### #2 — Cross-channel Bütçe Optimizatörü (+ projeksiyon)
- **Ne:** Kanal-üstü mevcut bütçeyi yeniden dağıtım önerisi: "Meta'dan ₺X'i Google'a kaydır → tahmini +%Y dönüşüm / +Z ROAS". Marjinal verim mantığıyla, projekte edilen etki ile.
- **Kimi nasıl geçer:** **Adin.ai'nin** çekirdek değerini (media optimizer + projeksiyon) KOBİ fiyatına indirir. **heyBooster**'da bütçe önerisi var ama kanal-içi/genel; AYAZ kanal-üstü tek havuz görür (M2 sayesinde). Funnel/Looker bunu hiç yapmaz.
- **Kullanıcı değeri:** En yüksek "para kazandıran" özellik — doğrudan ROAS'a dokunur, ödeme isteğini meşrulaştırır.
- **Build zorluğu: 3.** Veri ve derived metrikler var; gereken: marjinal-getiri/doygunluk modeli (önce basit, sonra eğri) + projeksiyon + güven aralığı. Yazma yok → salt öneri (düşük risk).
- **MVP dilimi:** Salt-okunur "öner ve göster" — pacing-eğrisi değil, son-dönem marjinal ROAS'a dayalı basit yeniden-dağıtım + "tahmini etki" bandı. Otomatik uygulama YOK (güven bariyeri). Copilot içinden de çağrılabilir ("bütçemi nasıl bölmeliyim?").

### #3 — Hedef Takibi + Tahmin/Pacing (forecasting)
- **Ne:** Kullanıcı hedef koyar ("bu ay ₺500K gelir / 2.000 dönüşüm"). AYAZ **ulaşır mı** tahmin eder (trend ekstrapolasyon + pacing), "yetişmek için günlük ne gerekir" der, sapınca uyarır.
- **Kimi nasıl geçer:** **heyBooster**'da KPI/hedef takibi var ama AYAZ bunu **forecast + Copilot anlatımı + bütçe önerisi (#2)** ile birleştirir. Adin forecasting'i var ama enterprise. Funnel/Looker'da yok.
- **Kullanıcı değeri:** "Yetişiyor muyum?" pazarlamacının #1 anksiyetesi; ay sonunu beklemeden müdahale. Aylık retention'ı doğrudan besler (her ay açma sebebi).
- **Build zorluğu: 2-3.** Zaman serisi + basit projeksiyon; `budget_pacing` narrator şablonu **zaten var** (`narrator.py:_narrate_budget_pacing`). Gereken: hedef modeli + pacing hesap + tahmin.
- **MVP dilimi:** Tek hedef tipi (dönüşüm veya gelir), lineer/sezon-ayarlı pacing, "yetişme olasılığı" + tek cümle Türkçe öneri.

### #4 — Alarm → Kök-Neden → Tek-Tık-Çözüm Döngüsü
- **Ne:** Mevcut alarm (M4) bir adım derinleşir: alarm → "neden" (hangi kampanya/adset tetikledi, drill-down) → **önerilen düzeltme + tek tık** (kural taslakla / kampanya öner). "Ne oldu → neden → ne yap → yap" tam döngü.
- **Kimi nasıl geçer:** **heyBooster** alarm verir, kök-nedene indirmez, çözümü kullanıcıya bırakır. AYAZ alarmı **aksiyona** bağlar (M4→M6→M9 zinciri). Bu, "salt içgörü"yü "operasyon"a çevirir — kimsede uçtan uca yok.
- **Kullanıcı değeri:** İçgörü-aksiyon boşluğunu kapatır; "wow → şimdi ne yapayım?" tıkanmasını çözer.
- **Build zorluğu: 2.** Dedektörler kampanya granülünde **zaten çalışıyor** (`ads.py` bunu kanıtlıyor); kural motoru var. Gereken: alarmı entity-drill + öneri + "kural oluştur" tek-tık akışına bağlamak.
- **MVP dilimi:** En sık 3 alarm tipinde (ROAS düşüşü, sıfır dönüşüm, harcama sıçraması) kök-neden entity + 1 önerilen kural taslağı. Otomatik yürütme opt-in.

### #5 — Doğal Dilde Rapor/Pano Oluşturucu
- **Ne:** "Meta vs Google son 30 gün ROAS ve harcama" → Copilot panoyu/raporu kurar. NL → dashboard config.
- **Kimi nasıl geçer:** **Looker Studio**'nun sürükle-bırak emeğini sıfırlar; **Funnel** dashboard'ı da manuel. Tek-çatıda + Türkçe + tek cümleyle.
- **Kullanıcı değeri:** Rapor kurma sürtünmesini yok eder; ajans için müşteri-başı rapor üretimini hızlandırır (M8 ile bileşik).
- **Build zorluğu: 3.** Dashboard motoru + metric layer var; gereken: NL → yapılandırılmış pano-şeması üretimi (Copilot'un bir aksiyon-tool'u olarak doğal yer alır).
- **MVP dilimi:** Copilot #1'in bir aksiyon-tool'u: NL'den önceden-tanımlı görsel setiyle pano taslağı; serbest düzen değil.

### #6 — Kreatif Performans Analizi
- **Ne:** Hangi reklam/görsel/metin tutuyor; yorgun (fatigue) kreatifleri işaretle; öneri.
- **Kimi nasıl geçer:** heyBooster'da creative içgörü var; Adin DAIVID ortaklığıyla. AYAZ ad-seviye fact ile yapabilir, ama **kreatif metadata/asset** çekimi gerektirir → en yüksek yeni-veri maliyeti.
- **Kullanıcı değeri:** Yüksek (kreatif = performansın en büyük kaldıracı) ama veri derinliği şart.
- **Build zorluğu: 4.** Ad-creative asset/metadata sync (konektör genişlemesi) + fatigue tespiti. Çekirdek dışı yeni veri.
- **MVP dilimi:** Önce ad-seviye performans sıralaması + fatigue (CTR düşüşü ad granülünde, dedektör hazır); asset görseli/AI değerlendirme sonra.

### #7 — Hafif Atıf / Marketing-Mix (MMM-lite)
- **Ne:** Hangi kanal dönüşümü gerçekten getiriyor — son-tık ötesi hafif çoklu-dokunuş veya regresyon-tabanlı katkı.
- **Kimi nasıl geçer:** Funnel üst pakette, Adin enterprise'da sunar. AYAZ "hafif + anlaşılır" sürümle KOBİ'ye indirir. CAPI (M7) first-party sinyali bunu güçlendirir → **bileşik avantaj**.
- **Kullanıcı değeri:** Yüksek ama "doğru/güvenilir mi" algı riski yüksek; yanlış MMM güveni yıkar.
- **Build zorluğu: 5.** Ekonometri/ML + metodoloji savunulabilirliği + eğitim. Veri olgunluğu ister.
- **MVP dilimi:** Tam MMM değil → "kanal katkı görünümü" (son-tık + CAPI destekli yardımcı-dönüşüm). Tam MMM açık-uçlu Ar-Ge.

### #8 — Benchmark / Kohort Zekâsı
- **Ne:** "Sektörünüzde ortalama CPC/ROAS X; siz Y'desiniz" — anonim kohort kıyas.
- **Kimi nasıl geçer:** Kimsede TR-sektör benchmark'ı net değil; **veri ağ etkisi** (müşteri arttıkça değer artar → savunulabilir uzun-vade hendeği).
- **Kullanıcı değeri:** Yüksek bağlam değeri ("iyi mi kötü mü?"), ama...
- **Build zorluğu: 3 (teknik) / yüksek (önkoşul).** Kritik kütle + KVKK-uyumlu anonimleştirme + kohort tanımı gerekir. **Müşteri sayısı az iken değersiz** → erken değil.
- **MVP dilimi:** Erteleme; ilk N yüzlerce tenant'a ulaşınca aktive et. Şimdi mimaride anonim-toplama hazırlığı yeterli.

> **Eklenen öneri (#1'in parçası):** **"Eski panellere dönme oranı = 0" kanca metriği** — Copilot'a "bu hafta ne kaçırdım?" özet komutu. Pazartesi-açılışı alışkanlığı kurar; retention'ın en güçlü davranışsal kancası. Düşük maliyet, yüksek alışkanlık etkisi.

---

## 3. Neden AI Copilot #1 — Bayrak Kama

**Tek cümle:** Copilot, *yeni bir modül değil; var olan 10 modülü tek bir Türkçe arayüzde erişilebilir ve aksiyon-alınabilir kılan meta-katman* — yani **bileşim hendeğini kullanıcıya görünür kılan yüzey**.

### Beş gerekçe

1. **En düşük build / en yüksek görünür fark.** Çekirdek hazır: `ClaudeNarrator` canlı (Claude API + fallback), her modül tipli servis fonksiyonu olarak tool'a hazır, Metric Layer tek doğruluk kaynağı. Çoğu rakip-üstünlüğü "yeni motor" değil "var olanı sarmalama" işi → build zorluğu 2.
2. **Her modülle bileşik (compounding).** Copilot tek başına chatbot; ama M2 üstünde **grounded** (uydurmaz), M4 ile içgörü çağırır, M6 ile kampanya okur, M3 ile rapor kurar, M9 ile kural taslaklar. **Yeni modül ekledikçe Copilot otomatik güçlenir** — sıfır marjinal arayüz maliyetiyle. Bu, tek-tek özellik değil **platform refleksi** yaratır.
3. **Rakibin yapısal olarak zor kopyaladığı yer.** Salt-veri rakipleri (Funnel/Coupler AI Chat) sohbet ekleyebilir ama **kanal-üstü + aksiyon + Türkçe domain** bağlamı yok — çünkü altta M4/M6/M9 yok. Copilot'un gücü modelden değil, **bağlandığı bileşimden** geliyor; bunu kopyalamak = 9 modülü kopyalamak.
4. **ICP'ye birebir.** ICP = "5-10 panel arasında gezen, kanal-üstü resmi göremeyen pazarlamacı." Copilot tam bu acıyı vurur: "tek soru = tüm kanallar + ne yapmalı." Junior'ı kıdemli gibi çalıştırır → KOBİ/ajans için somut.
5. **Türkçe = savunulabilir yerel kama.** Global Copilot'lar İngilizce/genel; Türkçe pazarlama jargonu + KVKK + yerel bağlam (kampanya dönemleri, ₺) ile kalibre bir Copilot, TR pazarında "yerli ve anlıyor" algısı yaratır — fiyat değil, **anlama** üzerinden farklılaşma.

**Risk & guardrail:** Halüsinasyon güveni anında yıkar. Bu yüzden v1 **salt-okunur tool'lar + her yanıtta zorunlu veri-alıntısı (citation)** + "veri yoksa söyle, uydurma" sıkı sistem komutu. Aksiyon (yazma) tool'ları opt-in ve onaylı.

---

## 4. Konumlandırma & Mesaj

**Kategori-tanımlayan tek cümle:**

> **"AYAZ, tüm dijital pazarlamanızı tek çatıda toplayan ve verinizi Türkçe konuşan bir pazarlama uzmanına dönüştüren AI kokpitidir — sadece 'ne oldu'yu göstermez, 'ne yapmalısın'ı söyler ve yapmanıza yardım eder."**

Kategori adı önerisi: **"AI Pazarlama Kokpiti"** (veri aracı değil, dashboard değil — *kokpit*: gör + anla + yönet tek yerde).

**3 kanıt noktası (proof points):**
1. **Tek doğruluk kaynağı:** 10 platform tek panelde, tek metrik tanımıyla (aynı ROAS her yerde aynı) — "10 sekme + tutarsız sayı" biter. *(M1+M2 canlı.)*
2. **Konuşan zekâ:** Sorularınızı Türkçe sorun, gerçek verinizden kaynak-gösterimli yanıt + sonraki adım alın. *(Copilot — `ClaudeNarrator` altyapısı canlı.)*
3. **Sürpriz fatura yok:** Sabit, anlaşılır ₺ abonelik (Funnel'in $800-6.000 öngörülemez flexpoint'inin tam tersi) + iyzico + KVKK-uyumlu yerli barındırma.

---

## 5. Ölçüm — Farklılaşma İşe Yarıyor mu?

| Aşama | Metrik | Hedef sinyali | Farklılaşmayı kanıtlayan |
|---|---|---|---|
| **Aktivasyon** | İlk kaynak bağlama → ilk Copilot sorusu | <24 saatte ilk soru | Copilot keşfediliyor mu |
| **"Aha" anı** | İlk grounded yanıt + ilk içgörüye dayalı aksiyon | İlk hafta ≥1 aksiyon | "Ne yap"ın değer yarattığı |
| **Copilot tutması** | Haftalık aktif soran kullanıcı oranı (WAU-Copilot) | Aktif tenant'ların >%40'ı | Bayrak kamanın yapıştığı |
| **"Eski panele dönme" ölçer** | Kendi-raporladığı/anket: "Google/Meta panelini açtın mı?" | Azalan trend | Tek-çatı vaadinin tutması |
| **Tutundurma** | Aylık aktif + bağlı kaynak sayısı; logo churn | Churn <%3/ay | Bileşim değerinin yapışması |
| **Genişleme (expansion)** | Tier yükseltme + kaynak/spend eşik aşımı + add-on | Net revenue retention >%110 | Modül-derinleştirmenin parayı çektiği |
| **Bileşim kanıtı** | Kullanıcı başına aktif kullanılan modül sayısı | Zamanla artan | Tek-katman değil platform kullanımı |

**Kuzey yıldızı:** **Haftalık aktif tenant'ların, Copilot'a soru sorup en az 1 aksiyon alma oranı.** Bu tek metrik üç tezi birden ölçer: tek-çatı (kanal-üstü soru), Türkçe AI (sorma), aksiyon (yapma).

**Karşı-metrik (guardrail):** Copilot yanıtlarında halüsinasyon/yanlışlık şikâyet oranı — eşiği aşarsa derinleştirmeyi durdur, grounding'i sertleştir.

---

## 6. Sıradaki 3 Derinleştirme Dalgası (önerilen sıra)

> İlke: önce mevcut çekirdeği **en düşük maliyetle en yüksek görünür farka** çevir (Copilot), sonra **en yüksek para-kazandıran** katmanı ekle (bütçe), sonra **retention kancasını** kur (hedef/pacing). Her dalga: tasarla → uzman ajanlarla yap → entegre → test → commit.

### Dalga 10 (şimdi) — **AYAZ AI Copilot v1 (salt-okunur, grounded, Türkçe)**
- **İçerik:** Tool-spec katmanı (mevcut servis fonksiyonlarını sarmala: `metrics`, `insights`, `ads`, `reports`) + sohbet oturumu/geçmiş + zorunlu veri-alıntısı + "uydurma" guardrail + Copilot UI (sohbet paneli + "bu hafta ne kaçırdım?" özet).
- **Neden ilk:** En düşük build (çekirdek hazır), en yüksek konumlandırma sıçraması, ICP'ye birebir, bileşim hendeğini görünür kılar. Pazar penceresi açık (rakipler henüz aksiyon-yönelimli + TR Copilot vermedi).
- **Kapsam dışı (v1):** Yazma/aksiyon tool'ları, NL-rapor oluşturucu (Copilot v2'ye), kreatif analizi.
- **Başarı testi:** Aktif tenant'ların >%40'ı haftalık soru soruyor; halüsinasyon şikâyeti eşik altında.

### Dalga 11 — **Cross-channel Bütçe Optimizatörü + Hedef/Pacing**
- **İçerik:** (a) Marjinal-ROAS tabanlı kanal-üstü yeniden-dağıtım önerisi + tahmini-etki bandı (salt öneri); (b) Hedef takibi + pacing/forecast ("yetişiyor musun") — `_narrate_budget_pacing` şablonu zaten var. İkisi de **Copilot içinden çağrılabilir** (bileşim).
- **Neden ikinci:** En yüksek para-kazandıran değer (ROAS'a doğrudan dokunur) + en güçlü retention kancası (hedef → her ay açma sebebi) birlikte. Adin'in çekirdeğini KOBİ'ye indirir.
- **Kapsam dışı:** Otomatik bütçe uygulama (yazma) — güven bariyeri; salt öneri kalır.
- **Başarı testi:** Öneriyi gören kullanıcının ≥1 bütçe değişikliği yapması; hedef koyan tenant oranı artışı.

### Dalga 12 — **Alarm→Kök-Neden→Tek-Tık-Çözüm + Copilot v2 (aksiyon tool'ları + NL-rapor)**
- **İçerik:** (a) Alarmı entity drill-down + önerilen kural taslağı + tek-tık'a bağla (M4→M6→M9 döngüsü); (b) Copilot'a aksiyon tool'ları (kural oluştur, NL'den rapor/pano kur) + onay akışı. Kreatif performans sıralaması (ad-seviye, dedektör hazır) bu dalgaya iliştirilebilir.
- **Neden üçüncü:** "İçgörü → operasyon" boşluğunu kapatır; Copilot'u danışmandan **asistana** yükseltir. Yazma-aksiyona ilk güvenli adım (taslak + onay, otomatik değil).
- **Kapsam dışı:** Reklam platformlarına doğrudan yazma (M6 faz 2 — ayrı güven/erişim süreci); tam MMM; benchmark (kritik kütle bekler).
- **Başarı testi:** Alarmdan kural oluşturma dönüşümü; aksiyon-tool kullanımının halüsinasyonsuz yapışması.

**Bilinçli ertelenenler:** Hafif atıf/MMM (#7, zorluk 5 + güven riski → veri olgunlaşınca), Benchmark/kohort (#8, kritik kütle önkoşulu), Kreatif AI-değerlendirme (#6 tam sürüm, yeni asset-sync maliyeti), Mobil (talebe bağlı), Reklam yazma/optimizasyon otomasyonu (M6 faz 2, ayrı güven süreci).

---

## En önemli tek açık soru

**Copilot v1 salt-okunur kalmalı mı, yoksa "tek-tık kural oluştur" gibi düşük-riskli aksiyonlar v1'e mi girmeli?** — Salt-okunur güveni hızlı kurar ama "asistan" vaadini geciktirir; erken aksiyon "wow"u büyütür ama halüsinasyon/yanlış-aksiyon güven riskini öne çeker. **Öneri:** v1 salt-okunur + alıntılı (güven inşası); aksiyon Dalga 12'de onaylı/taslak modunda. İlk 20-30 gerçek kullanıcının ilk hafta davranışıyla doğrulanmalı.
