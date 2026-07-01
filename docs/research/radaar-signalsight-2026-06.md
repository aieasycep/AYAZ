# AYAZ — Rakip Araştırması: RADAAR.io & SignalSight.io (2026-06)

> Kamuya açık kaynaklardan (resmi siteler WebFetch'e 403/egress engeli verdi → arama
> özetleri + 3. taraf siteler) + AYAZ repo durumu (birinci elden) ile derlendi.
> Panelin canlı UI'ı (kullanıcı ekran görüntüsü gönderecek) ile ayrıca netleştirilecek.
> Fiyat rakamları her iki üründe de **belirsiz/çelişkili** — canlı doğrulama şart.

---

## 1. RADAAR.io — Organik Sosyal Medya Yönetimi

**Ne / kime:** Çoklu sosyal profili tek panelden yöneten "en ucuz" sosyal medya suite'i
(planlama/yayın, içerik takvimi, sosyal inbox, dinleme, analitik + link-in-bio, URL
kısaltıcı, şifre/görev yöneticisi). ICP: solo/freelancer/KOBİ/küçük sosyal ajans.

**AYAZ ile kategori farkı:** RADAAR = **organik sosyal yayın**. AYAZ = **ücretli reklam +
analitik + feed + ölçümleme + Copilot**. Bitişik ama farklı. AYAZ'da sosyal yayın **yok**.

**RADAAR'ın zayıf karnı (= AYAZ'ın gücü):** sosyal dinleme zayıf, analitik kafa karıştırıcı,
iade/itibar şikâyetleri (Trustpilot). AYAZ birleşik metrik + açık analitik + KVKK + şeffaf
faturalama ile burada ayrışır.

### AYAZ-fit (credential ayrımı kritik)
| Alt-yetenek | AYAZ durumu | Değer | Efor | Kimlik gerekir? |
|---|---|---|---|---|
| İçerik takvimi / planlama | yok | Yüksek | Orta | **Hayır** |
| Çoklu-kanal taslak composer | yok | Yüksek | Orta | **Hayır** |
| AI caption/hashtag | kısmi (Copilot) | Yüksek | Düşük-Orta | Hayır |
| Müşteri onay akışı (guest) | kısmi (M8 rol/davet) | Yüksek (ajans) | Orta | **Hayır** |
| Zamanlama → **canlı yayın** | yok | Yüksek | Yüksek | **EVET** (her ağ ayrı OAuth + app review) |
| Sosyal inbox (DM/yorum) | yok | Orta-Yüksek | Çok yüksek | **EVET** |
| Sosyal dinleme | yok | Orta | Yüksek | EVET |
| Link-in-bio / URL kısaltıcı / şifre-görev yön. | yok | Düşük | — | **Kapsam dışı önerilir** |

**Öneri:** Şimdi tam "Sosyal modül" AÇMA (kapsam tuzağı + ağır kimlik bağımlılığı).
**No-cred "İçerik Planlayıcı" ince dilimi** (takvim + composer + onay + AI caption) yapılabilir;
canlı "Yayınla" butonu kimlik gelince eklenir. Farklılaştırıcı: **organik + ücretli tek
açık-metrikli kokpit** + "en iyi reklam kreatifini organik posta çevir" köprüsü.

---

## 2. SignalSight.io — Server-side Ölçümleme (AYAZ M7 ile aynı kategori)

**Ne / kime:** First-party sinyalleri toplayıp **tek bağlantıyla çok platforma** server-side
ileten dönüşüm-ölçümleme hub'ı (sGTM + Meta CAPI Gateway). Ürün ailesi: Web Conversions,
**App CAPI (SDK'sız)**, Offline Store Sales, **Lead Sync/CRM**, Web2App. ICP: performans
e-ticaret + mobil app reklamvereni + lead-gen. TR referansı var (heymommy.com.tr).

**Şeffaflık düşük:** public fiyat yok, G2'de review yok, Trustpilot'ta ~4 yorum → olgunluk
belirsiz. **KVKK ve Consent Mode v2 native desteği kamuya net değil** → AYAZ için fırsat.

### M7 GAP tablosu (AYAZ repo gerçeği)
| SignalSight yeteneği | AYAZ M7 | Gap |
|---|---|---|
| Collect endpoint + PII hash + consent + dedup | **var** | sağlam çekirdek |
| Meta CAPI / TikTok Events / GA4 MP | **var** | 3 hedef |
| Pinterest/Reddit/Snapchat/X/Google Ads Enhanced+Offline | **yok** | sadece 3 hedef (`_VALID_PLATFORMS`) |
| App CAPI (mobil, SDK'sız) | **yok** | — |
| Offline store sales | **yok** | — |
| Lead Sync / CRM (HubSpot/Zoho/Salesforce) | **yok** | — |
| **Consent Mode v2 / GCS / granular** | **yok** | sadece boolean consent |
| **Test-event / debug konsolu** | kısmi | ham log var; validator/dry-run/canlı debug yok |
| **Retry / dead-letter / monitoring** | kısmi/yok | failed kalır, retry yok |
| **Match-quality (fbc/fbp/external_id/IP/UA)** | kısmi | yapılandırılmış toplama yok (Meta EMQ) |
| First-party/custom domain (edge) | yok | snippet 3. taraf host'a atıyor |
| E-ticaret data-layer snippet (Purchase/AddToCart) | kısmi | sadece page_view |

### En değerli **kimliksiz** M7 iyileştirmeleri (hemen yapılabilir)
1. **KVKK/Consent Mode v2 birinci sınıf** — granular consent + GCS; reddedince consent-aware sinyal. (TR/EU farklılaştırıcı)
2. **Test-Event + Debug Konsolu** — payload validator + canlı olay akışı + dry-run + "neden skipped/failed". (öldürücü onboarding)
3. **Match-quality** — fbc/fbp/external_id/IP/UA toplama + "eşleşme kalitesi skoru".
4. **Dayanıklılık** — retry + backoff + dead-letter + tek-tık yeniden-gönder + sağlık paneli → M4 İçgörü'ye bağla.
5. **Destinasyon transform paritesi** (kod no-cred, token canlıda) — Google Ads Enhanced/Offline + Pinterest CAPI → sonra Reddit/Snapchat.
6. **E-ticaret hızlı kurulum snippet'i** — Shopify/İdeasoft/T-Soft/WooCommerce Purchase/AddToCart eşlemeli.
7. (faz 2) First-party/edge collect; (faz 2) App CAPI / Offline / CRM Lead Sync — **kimlik/altyapı bağımlı**.
8. **Birleşik kapanış** — M7 olaylarını M2/M3/Copilot'a besle: "kaç gönderildi/eşleşti/consent ile düştü" doğal dille.

**Öneri:** SignalSight'ı kapsam genişliğinde kovalamak yerine, AYAZ'ın birleşik veri+Copilot
avantajıyla **"TR e-ticaret için en güvenli, en kolay doğrulanan CAPI"** ol. Sıra: 1→2→3→4
(hepsi no-cred, yüksek değer) → 5,6 → faz 2 (7).

---

## Sonuç — öncelik
- **En yüksek no-cred ROI:** SignalSight-kaynaklı **M7 sertleştirme** (Consent Mode v2 + Test-Event konsolu + dayanıklılık + match-quality) — mevcut modülü güçlendirir, TR-first KVKK farklılaşmasına doğrudan oynar.
- **İkincil no-cred:** RADAAR-kaynaklı **İçerik Planlayıcı** ince dilimi (yeni yüzey; canlı yayın kimlik bekler).
- **Kimlik bekleyenler:** sosyal canlı yayın/inbox, yeni CAPI destinasyon token'ları, App/Offline/CRM, first-party edge domain.

> Panel ekran görüntüleri gelince bu bulgular UX detayıyla birleştirilip kesinleştirilecek.
