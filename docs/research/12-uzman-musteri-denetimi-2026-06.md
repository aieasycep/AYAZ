# AYAZ — 12 Sesli Uzman & Müşteri Denetimi + İyileştirme Yol Haritası (2026-06)

12 bağımsız "uzman/müşteri" panel testi (canlı demo veriyle, 37 ekranın tam-sayfa
görüntüleri + kod incelemesi) sentezi. Toplam **160 bulgu**: 20 kritik · 56 yüksek
· 54 orta · 30 düşük.

## Yöntem
- Yerel tam yığın (backend 4 worker + standalone prod frontend + Neon-eşi demo veri)
  ayağa kaldırıldı; 37 ekran Playwright ile temiz (CORS düzeltildikten sonra hatasız,
  gerçek veriyle) yakalandı.
- Her değerlendirici ekran görüntülerini GÖRDÜ + ilgili frontend/backend kodunu okudu,
  yapılandırılmış bulgu (ekran, kategori, önem, öneri) üretti.

## Değerlendiriciler ve verdict
**Pazarlama uzmanları (5):** Performance Marketing, Senior Digital (strateji), SEO,
Sosyal Medya, Data Analist → "olgun kapsam ama güven kırıkları var".
**Ürün/Tasarım (3):** Product Manager, UI/UX Designer, Art Direktör → "doğru kategori,
temiz arayüz; demo olgunluğu eşiğinde takılı (tutarsızlık + aktivasyon)".
**Müşteri pilotları (4):**
- Çok müşterili ajans → **evet-eksiklerle** (portföy/SMTP/konsolide fatura eksik)
- Tekstil e-ticaret → **evet-eksiklerle** (feed olgun; SKU/iade boyutu yok)
- Omnichannel perakende (Teknosa benzeri) → **kararsız** (offline/ROPO/marketplace yok)
- Solo freelancer → **evet-eksiklerle** (white-label ₺12.900'e kilitli, PDF yok, tier boşluğu)

## Kritik temalar (🔴)
1. **Tek gerçek kaynak / metrik tutarlılığı** — dönüşüm oranı %2,64 (reklam) vs %15
   (huni); öneri ROAS'ı kampanya tablosuyla çelişiyor; "Son 30 gün" ekranlar arası
   1 gün kayık; "en güçlü kanal" harcamaya göre seçiliyor (ROAS değil).
2. **Kırık çekirdek uçlar** — Günlük Brifing boş/404, Bütçe Planlayıcı 503 + yanlış
   "Çevrimdışısınız" mesajı + ham JSON hata gösterimi.
3. **SEO sözleşme uyumsuzluğu** — backlink / anahtar kelime / Lighthouse, veri dönse
   bile frontend-backend uyumsuzluğundan ekrana hiç gelmiyor.
4. **Demo ilk açılış bozuk** — kırmızı "Plan Limiti Aşıldı" alarmı (Free + 5 kaynak),
   boş brifing/hedefler, iki çelişen onboarding (1/4 vs 4/5), entegrasyon 5 vs 0,
   AYAZ/EasyCep marka karışıklığı.

## Yüksek temalar (🟠)
5. Sağlık Endeksi yanıltıcı (Dönüşüm 100/100 — şişkin huni oranından).
6. İçgörü/skor → aksiyon köprüleri kopuk (butonlar bağlamsız sabit sayfalara gidiyor).
7. Demo seed eksikliği — birçok modül boş görünüyor (hedef/otomasyon/brifing/plan).
8. CSV/Excel **+ PDF** dışa aktarım yok (analiz ekranlarının hiçbirinde).
9. Huni güvenilirliği — 40 ham olaya dayalı yüzdeler; "EN BÜYÜK DÜÜŞ" yazım; çelişen rozetler.
10. Ölçümleme/CAPI veri kalitesi (%10 hata, GA4 rıza yok, 32/100 eşleşme) atıfı bozuyor.
11. **Fiyatlandırma**: white-label sadece Agency (₺12.900); Starter↔Agency arası
    freelancer/pro tier boşluğu; free plan kullanılamaz (1 kaynak/7 gün).
12. KVKK Rıza Merkezi'ndeki hedef-bazlı iletim sayıları gerçek değil (kodda kabul edilmiş).

## Segmente özel büyük boşluklar (🟡 — yol haritası, L efor)
- **Ürün/SKU boyutu** (DimProduct: item_id, koleksiyon, kategori) + **mağaza/lokasyon**
  (DimStore) — tekstil & omnichannel için şart.
- **Gerçek ciro + iade + offline/ROPO + marketplace** (Trendyol/Hepsiburada) — omnichannel.
- **Ajans**: cross-workspace portföy ekranı, konsolide/müşteri-başı fatura, zamanlı rapor
  e-postası (gerçek SMTP/SES), white-label markasının workspace'ten miras alması.

## Uygulama dalgaları
### Dalga 1 — Demo + güven + doğruluk (hızlı kazanım + kritik fonksiyonel)
- Seed: demo planını yükselt (limit alarmı kalksın), marka tutarlılığı (AYAZ/EasyCep),
  boş modülleri doldur (hedef/otomasyon/brifing/bütçe planı/takvim).
- "En güçlü kanal" ROAS bazlı; "Son 30 gün" tek tanım; öneri ROAS pencere etiketi.
- HTTP-koda duyarlı hata mesajları (ham JSON yok; 5xx≠çevrimdışı).
- Brifing/bütçe uçlarını nazik boş-durum (404/503 yerine 200).
- Huni: yazım + rozet sadeleştirme + düşük örneklem uyarısı.
- Öneri kartlarındaki tekrar eden global sağlık rozetini kaldır.

### Dalga 2 — Değer & dönüşüm
- İçgörü/skor → aksiyon köprüleri (bağlam taşıyan derin linkler; satır-bazlı aksiyon).
- CSV/Excel + markalı PDF export (paylaşılan bileşen).
- Sağlık Endeksi kalibrasyonu (gerçekçi benchmark).
- SEO sözleşme uyumu (backlink/kelime/Lighthouse render) + fırsat motoru kalibrasyonu.
- Fiyat paketleri: Freelancer/Pro tier + white-label'ı uygun plana indir.
- Tek "Bütçe Aracı" (optimizer + simülatör sekme); ölçümleme veri kalitesi vurgusu.

### Dalga 3 — Segment derinliği (büyük)
- Ürün/SKU + lokasyon veri modeli (DimProduct/DimStore).
- Gerçek ciro/iade + offline conversion/ROPO + marketplace connector.
- Ajans portföy görünümü + konsolide fatura + gerçek SMTP zamanlı rapor.

Kaynak ham bulgular: `scratchpad/all_findings.json` (12 değerlendirici, 160 bulgu).
