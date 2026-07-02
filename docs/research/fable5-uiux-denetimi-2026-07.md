# AYAZ Panel — Fable 5 UI/UX Denetimi (Temmuz 2026)

**Kapsam:** 41 masaüstü ekranı (tüm rotalar + sekme varyantları), 8 mobil (390px), 4 koyu tema — tamamı gerçek demo verisiyle, full-page yakalama. Bulgular ekran görüntüsüne ve/veya koda karşı tek tek doğrulandı; veri kaynaklı (seed) yanılsamalar elendi.

**Metodoloji:** 9 mercek (görsel hiyerarşi, tasarım sistemi tutarlılığı, bilgi mimarisi, ilk kullanım/güven, veri görselleştirme, Türkçe metin, mobil, koyu tema, erişilebilirlik). İlk tur çok-ajanlı koşuda 86 ham bulgu üretilmiş ve 63'ü hakem doğrulamasından geçmişti; altyapı kesintileri sonrası denetim ana oturumda uçtan uca yeniden yürütüldü ve bulgular birleştirildi.

---

## Genel Değerlendirme

Panel bütün olarak **olgun ve tutarlı bir tasarım sistemine** sahip: kart dili, rozetler, boş durumlar, gruplu navigasyon ve açık/koyu tema büyük oranda oturmuş. Komuta Merkezi → modül kartları köprüleri, Ürün Performansı'ndaki "iade uyarısı" bandı, denetim ekranındaki isimlendirilmiş reklamlar gibi "aksiyon söyleyen" desenler rakip ürünlere göre gerçek fark yaratıyor. Koyu tema örneklenen ekranlarda sızıntısız.

Ana zayıflık iki kümede toplanıyor: **(1) Sayı/dil yerelleştirmesi** — AI/şablon metinleri İngilizce sayı biçimi ve ASCII Türkçe ile üretiliyor; ürünün "AI size Türkçe söyler" vaadiyle en görünür çıktısı çelişiyor. **(2) Ekranlar arası anlam tutarlılığı** — aynı hedef iki ekranda zıt durum gösteriyor, harcama artışı bir ekranda yeşil bir ekranda kırmızı. Bunlar tek tek küçük ama toplamda "veriye güven" duygusunu aşındırıyor; çoğu düşük eforlu, merkezî düzeltmelerle kapanır.

---

## En Kritik 10 Bulgu

1. **Hedef ilerleme yüzdesi hatalı (backend `pct_to_target`)** — P1 · Yönetici Görünümü üç hedefte de "%1 / Hedef 6.000" ve boş çubuk gösteriyor; Öneri Merkezi "Hedefe Yüzde: %1 (mevcut 3 / hedef 4)" diyor (gerçek %75). Hedefler ekranı aynı hedefi doğru (dolu çubuk, %140,7) gösteriyor → iki ekran birbirini yalanlıyor, RİSKLİ/YOLUNDA rozetleriyle çelişiyor. *Öneri: pct hesabını tek serviste düzelt (oran×100), tüm ekranlar aynı alanı okusun.*

2. **Harcama hedefi aşımı "başarı" gibi kutlanıyor** — P1 · "Google Ads Harcama Hedefi": ₺251.192 / hedef ₺180.000 (%40 aşım) yeşil çubuk + "YOLUNDA" + "Hedef yolunda gidiyor!" (Hedefler, Brifing, Yönetici). Bütçe hedefinde aşım kötüdür. *Öneri: hedef tipine yön semantiği ekle (spend=düşük iyi); aşımda turuncu/kırmızı + "Bütçe aşıldı" metni.*

3. **AI/şablon metinleri ASCII Türkçe** — P1 · Brifing hero: "Dun ROAS %1.0 geriledi (2.74x); kampanya ayarlarinizi gozden gecirin."; hedef notları: "Donem sona erdi. Hedefe ulasilamadi", "%140.7'ine ulasmis durumda". Ürünün en vurgulu cümlesi bozuk Türkçe. Ek: hitap 'sen' ("gerisindesin") — ürünün kalanı 'siz'. *Kaynak: `briefing.py`, `goals.py` şablonları. Öneri: şablonları gerçek Türkçe karakterle + siz hitabıyla yeniden yaz.*

4. **Sayı biçimi kaosu (TR/EN karışımı)** — P1 · Yönetici/Öneri AI özeti: "₺398,123 harcama, ₺1,301,656 gelir" (EN binlik virgülü — TR gözü 398 lira okur); "3.27x", "%9.9". İçgörü metinleri: "Güncel değer: 3.244" (ROAS ama üç bin gibi). Aynı ekranda KPI kartları doğru TR biçimde ("₺398.123", "3,27x") → çelişki bariz. Simülatör girişleri ham "161460.59". *Öneri: backend metin üretimini tek tr-TR biçimlendiriciden geçir; input'lara maskeli biçim.*

5. **Ham teknik kimlikler arayüze sızıyor** — P1 · Kanal anahtarları `google_ads / meta_ads / tiktok_ads` Panel tablosunda, Reklam Yönetimi'nde, içgörü etiketlerinde, hedef kartında; aynı veri başka kartlarda "Google Ads" diye düzgün. Daha kötüsü: içgörüde ham UUID — "Etkilenen: 0aa29fac-10d3-424b-9715-f3a6bd934a34" (etiket + cümle içinde). *Öneri: merkezi kanal-etiket haritası; kural içgörülerinde kampanya adı çözümle.*

6. **Tarih/ay girişleri İngilizce-ABD biçiminde** — P1 · Native date input "06/03/2026" (TR kullanıcı 6 Mart okur; gerçek: 3 Haziran), ay seçici "August 2026" (Panel, Reklam Yönetimi, Bütçe Aracı, Bütçe Planlayıcı). *Öneri: input'lara `lang="tr"` / özel date-picker; en azından yanına ISO etiket.*

7. **Landing ↔ uygulama fiyat çelişkisi** — P1 · Landing 4 plan gösterip **Growth ₺4.900'ü "Önerilen"** yapıyor; uygulama içi Faturalama 5 plan (Pro ₺2.490 dahil) ve **Pro'yu "Önerilen"** gösteriyor. Satın alma anında güven sorunu. *Öneri: landing fiyat bölümünü billing PLANS'tan üret ya da elle eşitle.*

8. **Mobilde tablolar sütunları sessizce kesiyor** — P1 · 390px'te Panel kanal tablosunda 8 sütunun 4'ü görünüyor; Ürün Performansı'nda başlık ortadan kesik ("BRÜ|T ROAS") — kaydırılabilirlik ipucu (gölge/ok) yok, kullanıcı veri eksik sanır. *Öneri: overflow konteynerine kenar gölgesi + "kaydır" ipucu; mobilde öncelikli sütun seti.*

9. **Harcama artışı renk semantiği ekranlar arası zıt** — P1 · Brifing "HARCAMA ▲ %3,1" KIRMIZI (maliyet artışı=kötü — doğru); Yönetici "TOPLAM HARCAMA ▲ %35,7" YEŞİL; Panel "En Çok Değişenler" +%56,1 YEŞİL. Aynı olay bir ekranda alarm, diğerinde başarı. *Öneri: NEGATIVE_IS_GOOD kümesini paylaşılan yardımcıya taşı, her delta oradan renklensin.*

10. **Hedef durum rozeti ad/renk tutarsızlığı** — P2 · Aynı durum Yönetici'de kırmızı "RİSKLİ", Hedefler/Brifing'de turuncu "RİSK ALTINDA". *Öneri: tek eşleme sabiti (at_risk → "Risk Altında", turuncu).*

---

## Hızlı Kazanımlar (düşük efor)

- "CSV Indir" / "Indiriliyor..." → "CSV İndir" / "İndiriliyor..." (dashboard + creatives, kodda teyitli).
- TR-locale `text-transform: uppercase` İngilizce kelimeleri bozuyor: "RETARGETİNG", "VİRAL CREATİVE", "DESTİNATİONS" → başlıklarda uppercase'i CSS yerine veri katmanında yap ya da `lang` düzelt.
- Sıfır-kötü-haber rozetleri alarm renginde: Sağlık Endeksi "0 zayıf" ve Benchmark "Zayıf 0" kırmızı çip → sıfırsa nötr/gri göster.
- Dönüşüm adet metriği ondalıklı: "4.682,32", "212,53" → tüm ekranlarda tam sayı.
- Brifing alt bölümü "İÇERİK ÖNERİLERİ" başlığı altında gezinme kısayolları → "İlgili Ekranlar" / "Başlamak İçin" (Raporlar'daki doğru kalıpla eşitle).
- Benchmark metrik adları gereksiz kırpılıyor ("Reklam Harcama Getirisi (…") → etiket sütununu genişlet/sar.
- Öneri kartlarındaki ikinci çip çifti etiketsiz ("YÜKSEK", "Orta") → "Etki: Yüksek · Efor: Orta".
- Onboarding %100 ekranı çıkışsız → "Panele git" / "Raporları incele" butonları ekle.
- Simülatör KPI satırında HARCAMA deltası "—", diğerleri "%0,0" → tutarla; grafik legend kareleri bar renkleriyle eşleşsin.
- Yüzde yerleşimi ("%15" vs "15,0%") ve bin kısaltması ("24K" vs "2,2B") → tek sözleşme (öneri: %X ve B yerine K değil "24 B" yerine tutarlı tek harf seç, tercihen "K" yaygın anlaşılır ya da tam sayı).

## Yapısal İyileştirmeler

- **Yerelleştirme boru hattı:** Backend'in ürettiği TÜM kullanıcı metinleri (brifing, hedef notu, içgörü, öneri, AI özet) için tek Türkçe sayı/tarih biçimlendirme yardımcı katmanı; şablonların Türkçe karakter denetimi CI'da basit bir regex testiyle korunabilir.
- **Semantik renk sözleşmesi:** metrik yönü (yüksek-iyi / düşük-iyi) tek modülde tanımlanıp delta rozetleri, hedef durumları ve grafik vurguları oradan beslenmeli.
- **Genel Bakış yoğunluğu:** Komuta Merkezi ile Yönetici Görünümü'nün üst yarısı birebir aynı (aynı AI cümlesi + aynı 4 KPI). Orta vadede: Yönetici'yi hedef/rapor odaklı sadeleştir ya da ikisini birleştir.
- **Mobil tablo stratejisi:** geniş tablolar için mobilde kart-satır dönüşümü veya sabit ilk sütun + yatay kaydırma göstergesi.

## Ekran Bazında Özet

| Ekran | Öne çıkan sorun |
|---|---|
| Günlük Brifing | ASCII Türkçe hero + sen/siz karışımı + nokta ondalık |
| Yönetici Görünümü | %1 hedef çubukları + EN sayı biçimli AI özeti + yeşil harcama artışı |
| Hedefler | Harcama hedefi aşımı "YOLUNDA"; ASCII notlar; ISO tarih |
| Öneri Merkezi | %1 hedef çipi; EN sayı biçimi; etiketsiz çipler |
| İçgörüler | Ham UUID sızıntısı; nokta ondalıklar; ham metrik/kanal etiketleri |
| Panel | Ham kanal anahtarları; ABD tarih inputu; CSV Indir; skor kartında nokta ondalık |
| Reklam Yönetimi | Ham kanal anahtarları; TR-uppercase İngilizce başlıklar |
| Bütçe Aracı (Senaryo) | Ham input değerleri; "2,2B" ekseni; legend renk uyumsuzluğu |
| Sektör Kıyaslama | Kırpık metrik adları; kırmızı "Zayıf 0" çipi |
| Sağlık Endeksi | Kırmızı "0 zayıf"; boş üst kart düzeni |
| Landing | Fiyat/önerilen plan uygulamayla çelişiyor |
| Mobil (genel) | Tablo sütunları ipuçsuz kesiliyor |
| Koyu tema | Örneklenen ekranlarda sorun yok ✔ |

*Denetim: Fable 5 — 9 mercek, ekran+kod çapraz doğrulama. Temmuz 2026.*

---

## Düzeltme Durumu (2 Temmuz 2026)

Denetimdeki 23 bulgunun tamamı aynı gün 8 commit'te kapatıldı (PR #2).
Her commit backend (2994) + frontend (595) test paketi ve production
build ile doğrulandı; kritik ekranlar gerçek demo verisiyle yeniden
görüntülenerek teyit edildi.

| Commit | Kapsam |
| --- | --- |
| `85be511` | Hedef yüzdesi oran/yüzde karışıklığı; harcama hedefi yön semantiği; hedef notları gerçek Türkçe |
| `a0429b8` | AI/şablon metinleri (brifing, narrator, otomasyon): TR karakter + TR sayı + UUID sızıntısı; ortak `trformat.py` |
| `64f7109` | Ham kanal anahtarları (panel/reklam); delta renk sözleşmesi (`channels.ts` NEGATIVE_IS_GOOD); rozet adları; çip/başlık cilaları |
| `e8c1cac` | Onboarding %100 CTA'ları; simülatör (tam sayı girdi, tutarlı delta, lejant, K ekseni); optimizer otomatik hesap |
| `4f9e003` | Landing fiyat senkronu (5 plan, Önerilen=Pro); mobil tablo kaydırma gölgesi; hedef kartı TR tarih; yüzde önek standardı (13 ekran) |
| `3ce4138` | Optimizer yüzde/kesir birim hatası (otomatik çalıştırmanın açığa çıkardığı gerçek 422); optimizer kanal etiketleri + TR gerekçe |
| `e946374` | ads.py önerileri + fixes.py kök-neden şablonları TR biçim; yönetici içgörü çipi etiketi |
| `add99b6` | Copilot özet cevapları, kreatif yorumu, sağlık endeksi notları TR biçim |

**Bilinçli ertelenenler (orta vadeli, yapısal):** Yönetici ↔ Komuta
Merkezi üst yarı birleştirmesi; özel Türkçe date-picker (native input
tarayıcı diline bağlı — `html lang="tr"` doğrulandı, gerçek TR
kullanıcıda tarih TR biçimde görünür).

**Not:** Demo verisindeki eski biçimli *saklanan* içgörü/brifing
kayıtları tekilleştirme nedeniyle yeniden yazılmaz; yeni üretilen tüm
metinler düzeltilmiş şablonlardan çıkar.
