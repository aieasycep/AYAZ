# AYAZ — Ekip Personaları, İhtiyaç Haritası ve Geliştirme Yol Haritası

> Vizyon: Bir şirketin pazarlama organizasyonundaki **her rol** (performans, marcom/kreatif,
> müşteri hizmetleri, planlama, yönetim) işini **tek panelden** yapabilsin; herkes kendi
> diliyle analiz/içgörü alsın, aksiyonu da aynı panelden alsın.
>
> Bu belge her personayı ve onun en ince ihtiyacını çıkarır, AYAZ'ın mevcut durumunu
> (🟢 var / 🟡 kısmi / 🔴 yok) işaretler, kimlik/altyapı bağımlılığını ve önceliği verir.

---

## Persona 1 — Performans Pazarlamacısı (Digital / Performance Marketer)

**İşi:** Reklam harcamasını ROAS/CPA hedeflerine göre yönetmek, kampanyaları optimize etmek.

| İhtiyaç | Durum | Kimlik? |
|---|---|---|
| Tüm kanallarda birleşik ROAS/harcama/CTR/CPC/CPA (tek tablo) | 🟢 M2/M3 Dashboard | Reklam OAuth |
| Kanal/kampanya/reklam kırılımı + dönem karşılaştırma | 🟢 Dashboard + Top Movers | " |
| Anomali/alarm (ROAS düştü, harcama fırladı) + kök-neden | 🟢 M4 İçgörü + Optimizer | " |
| "ROAS < x ise durdur" otomasyon kuralları | 🟢 M9 Otomasyon | " |
| Server-side ölçümleme / CAPI + eşleşme kalitesi + dayanıklılık | 🟢 M7 (Dalga 52-60) | CAPI token |
| **Aylık bütçe planı + platform/kampanya alokasyonu** | 🟡→🟢 **M12 (yapılıyor)** | **Hayır** |
| Doğal dille soru–cevap ("kampanyalarım nasıl?") | 🟢 Copilot | Reklam OAuth |

**Sonuç:** En olgun persona. Eksik tek büyük parça **bütçe planlama** → şimdi inşa ediliyor.

---

## Persona 2 — Marcom / Kreatif Ekibi

**İşi:** Marka mesajını ve kreatifleri üretmek; hangi görselin/mesajın işe yaradığını
**performans jargonu olmadan** anlamak; organik sosyal içeriği planlamak ve yayınlamak.

| İhtiyaç | Durum | Kimlik? |
|---|---|---|
| "Hangi kreatif/görsel ne kadar trafik/etkileşim getirdi" — marcom diliyle | 🟡 M6 Kreatifler (ROAS odaklı; marcom lensi gerek) | Reklam OAuth |
| Kreatif → organik içerik köprüsü (iyi reklamı organik posta çevir) | 🟢 Dalga 57 | Hayır |
| İçerik takvimi + composer + onay akışı + AI açıklama | 🟢 M11 (Dalga 56-58) | Hayır |
| **Tek tıkla sosyal medyaya yayın** | 🔴 Kilitli (501) | **EVET** (her ağ OAuth + app review) |
| Marka varlıkları / kreatif kütüphanesi (görsel deposu) | 🔴 yok | Depolama |
| Kreatif A/B karşılaştırma, "kazanan mesaj" özeti | 🟡 kısmi | Reklam OAuth |

**Yapılacak (no-cred):** **Marcom Kreatif Lensi** — kreatif performansını dönüşüm/etkileşim
hikâyesi olarak gösteren, görsel-öncelikli bir görünüm ("bu görsel 12.400 tıklama, %3,1 CTR,
en çok 25-34 yaş"). Canlı yayın kimlik bekler; planlama/onay/AI hazır.

---

## Persona 3 — Müşteri Hizmetleri / Sosyal Bakım (Social Care)

**İşi:** Sosyal medyadan gelen DM, yorum ve bahsetmeleri (mention) görüp **panelden doğrudan**
yanıtlamak — RADAAR'ın güçlü olduğu alan.

| İhtiyaç | Durum | Kimlik? |
|---|---|---|
| Birleşik sosyal gelen kutusu (DM + yorum + mention, çok kanal) | 🔴 yok | **EVET** (okuma OAuth) |
| Panelden doğrudan yanıt / yorum cevaplama | 🔴 yok | **EVET** (yazma OAuth) |
| Konuşma atama (temsilciye), durum (açık/çözüldü), etiket | 🔴 yok | Hayır (iş akışı) |
| Hazır yanıtlar (canned replies) + AI yanıt önerisi | 🔴 yok | Hayır (AI mock) |
| SLA / ilk yanıt süresi, yoğunluk raporu | 🔴 yok | Hayır |
| Duygu analizi (olumlu/olumsuz) + önceliklendirme | 🔴 yok | Hayır (AI) |

**Yapılacak (no-cred kabuk):** **Sosyal Gelen Kutusu modülü** — iş akışı (atama/durum/etiket),
hazır yanıt + AI yanıt önerisi, duygu etiketi, SLA paneli; **demo/seed veriyle çalışır**, canlı
senkron + gönderim kimlik gelince açılır (yayınla gibi gate'li). Bu, RADAAR paritesinin kalbi.

---

## Persona 4 — Planlama / Bütçe Sorumlusu

**İşi:** Gelecek dönemin harcama planını yapmak; bütçeyi kanal/kampanya bazında dağıtmak.

| İhtiyaç | Durum | Kimlik? |
|---|---|---|
| "Temmuz için plan oluştur → toplam bütçe gir → akıllı alokasyon" | 🟡→🟢 **M12 (yapılıyor)** | **Hayır** |
| Hedefe göre alokasyon (ROAS / dönüşüm / dengeli) | 🟢 (M12) | Hayır |
| Beklenen sonuç projeksiyonu (dönüşüm/gelir/ROAS) | 🟢 (M12) | Hayır |
| Manuel ince ayar + senaryo karşılaştırma | 🟡 (M12 v1 öneri; senaryo sonra) | Hayır |
| Plan vs gerçekleşen takibi (ay içinde) | 🔴 sonraki dalga | Reklam OAuth |
| Pacing uyarısı (bütçe erken/yavaş tükeniyor) | 🟡 M? (hedef pacing var) | Reklam OAuth |

**Yapılıyor:** M12 Bütçe Planlayıcı (alokasyon + projeksiyon + kaydetme). Sonra: plan-vs-gerçekleşen + senaryo.

---

## Persona 5 — CEO / CMO (Yönetici)

**İşi:** Teknik detaya girmeden "pazarlamada neler oluyor"un tek-bakışta cevabını almak;
düzenli, sade, üst-düzey rapor.

| İhtiyaç | Durum | Kimlik? |
|---|---|---|
| Yönetici özeti: toplam harcama, gelir, ROAS, MoM trend | 🟡 Dashboard + Brifing (yönetici lensi gerek) | Reklam OAuth |
| Hedeflere ilerleme + forecast/pacing | 🟢 M-Hedefler | " |
| Kanal ROI karşılaştırma + "nereye yatırım dönüyor" | 🟡 kısmi | " |
| Otomatik, zamanlı, white-label PDF/e-posta yönetici raporu | 🟢 M3 Raporlar (yönetici şablonu eklenebilir) | E-posta(SMTP) |
| Doğal dille "bu çeyrek nasıl gitti?" | 🟢 Copilot | " |
| Günlük proaktif AI brifing | 🟢 Brifing | " |

**Yapılacak (no-cred):** **Yönetici (CMO) Görünümü** — tek ekran üst-düzey özet (KPI kartları +
trend + kanal ROI + hedef durumu + en kritik 3 içgörü), "Yönetici Raporu" şablonu.

---

## Çapraz-kesen ihtiyaçlar (tüm ekipler)

- **Rol bazlı görünüm & izin (RBAC):** M8 rol altyapısı var (owner/admin/member). Ekip-bazlı
  varsayılan görünüm + ince izin (ör. CS sadece inbox, marcom sadece içerik) → derinleştirilebilir.
- **Bildirim & atama:** M-Bildirimler var; ekip içi atama/mention (inbox + içerik onay) eklenebilir.
- **Mobil:** PWA var; saha/yönetici için mobil özet yeterli.
- **Dil/TR-first + KVKK:** çekirdek; sürdür.

---

## Öncelikli geliştirme sırası (no-cred önce — değer/efor)

1. **M12 Bütçe Planlayıcı** — Planlama personası; tam fonksiyonel, kullanıcının net istediği. **(yapılıyor)**
2. **Sosyal Gelen Kutusu (kabuk + iş akışı + AI yanıt + duygu)** — CS personası; RADAAR paritesi; demo veriyle çalışır, canlı kimlik gate'li.
3. **Yönetici (CMO) Görünümü + Yönetici Raporu şablonu** — CEO/CMO personası; mevcut veriden, no-cred.
4. **Marcom Kreatif Lensi** — marcom personası; kreatif performansını marka diliyle, no-cred.
5. **Plan vs Gerçekleşen + senaryo karşılaştırma** (M12 faz 2) — planlama derinleştirme.
6. **Copilot'a yeni modül farkındalığı** (bütçe planı, inbox, kreatif) — birleşik kokpit.

**Kimlik/altyapı bekleyenler (operatör tarafı):** canlı sosyal yayın & inbox senkronu (her ağ
OAuth + app review), reklam OAuth app'leri + app review, gerçek ödeme, SMTP, üretim alan adı.
Bunlar kod değil kurulum/onay adımıdır; ürün mimarisi bunlara hazır.
