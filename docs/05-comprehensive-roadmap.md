# AYAZ — Kapsamlı Ürün Yol Haritası

> Hedef: **bir dijital pazarlama uzmanının ihtiyaçlarının büyük çoğunluğunu tek platformda** karşılamak.
> Basit bir dashboard DEĞİL — uçtan uca bir dijital pazarlama işletim sistemi.
> Bu belge yaşayan kapsamdır; ekip her dalga sonunda günceller. Otonom ilerleme: ekip
> kararları kendi alır, kullanıcıya bağımlı işler `06-user-todo.md`'de toplanır.

## Modül Haritası ve Durum

| Modül | Açıklama | Referans | Durum |
|---|---|---|---|
| **M1 — Bağlantı Hub'ı** | Çok platformlu konektörler, OAuth, otomatik sync, sağlık izleme | Funnel.io | 🟢 10 konektör + OAuth + Vault + scheduler (canlı veri için kimlik bekliyor) |
| **M2 — Birleşik Veri + Metrik Katmanı** | Normalize tek doğruluk kaynağı, türetilmiş metrikler | Funnel.io | 🟢 Çekirdek hazır |
| **M3 — Dashboard & Raporlama** | Özelleştirilebilir panolar, görseller, kıyas, zamanlı PDF/e-posta, paylaşılabilir/white-label müşteri raporu | Looker Studio | 🟢 Pano + zamanlı/paylaşılabilir white-label rapor (PDF ileride) |
| **M4 — AI İçgörü & Uyarı** | Anomali tespiti, Türkçe doğal-dil içgörü/öneri, e-posta/Slack uyarı | heyBooster | 🟢 Hazır (6 dedektör + Türkçe narrator + uyarı kuralları) |
| **M5 — Feed Yönetimi** | Tek feed → kurallarla kanal-özel çıktı + her kanal için ayrı feed URL'i (Google Shopping, Meta katalog, vb.) | Channable | 🟢 Hazır (public feed URL dahil) |
| **M6 — Reklam Yönetimi & Optimizasyon** | Kanal-üstü kampanya görünümü, düzenleme, bütçe/teklif kuralları, optimizasyon önerisi | Adin.ai | 🟢 Okuma + öneri hazır (yazma/optimizasyon faz 2) |
| **M7 — Server-side Ölçümleme (CAPI)** | Meta CAPI, TikTok Events, GA4 MP + KVKK rıza | SignalSight | 🟢 Hazır (toplama endpoint + hash/consent/dedup + 3 platform iletimi) |
| **M8 — Çoklu Hesap / Ajans** | Workspace, müşteri yönetimi, white-label, roller | — | 🟢 Hazır (workspace + üye/rol + white-label + switcher) |
| **M9 — Otomasyon & Kurallar** | "ROAS < x ise kampanyayı durdur" tarzı kural motoru, zamanlı görevler, bildirim | — | 🟢 Hazır (kural motoru + audit + celery beat) |
| **M10 — Abonelik & Faturalama** | iyzico/Stripe, planlar, entitlement, kullanım | — | 🟢 Plan/entitlement/gating + sağlayıcı stub hazır (canlı için kimlik bekler) |
| **Platform** | Auth/RBAC/multi-tenant, OAuth Broker + Vault, scheduler, observability, KVKK | — | 🟢 Auth + OAuth Broker + şifreli Vault + Celery scheduler hazır |

Durum: 🟢 hazır · 🟡 kısmi · 🔵 yapımda (bu dalga) · 🔴 planlı

## Dalga Planı (otonom yürütülür)

- **Dalga 1 (tamamlandı):** Backend temeli, 6 konektör, sync+metrik+dashboard API, web paneli, canlı doğrulama.
- **Dalga 2 (tamamlandı):** OAuth Broker + Vault + Celery scheduler · **Feed Yönetimi (M5)** + public feed URL · Feed/Bağlantılar UI.
- **Dalga 3 (tamamlandı):** AI İçgörü & Uyarı motoru (M4) · 4 yeni konektör (LinkedIn, Microsoft, Criteo, Pinterest) · İçgörü UI + CPC cilası.
- **Dalga 4 (tamamlandı):** Zamanlı/paylaşılabilir & white-label raporlar (M3+) · Reklam Yönetimi okuma + öneri (M6) · ilgili UI'lar.
- **Dalga 5 (tamamlandı):** Otomasyon & Kurallar motoru (M9) · demo seed zenginleştirme · Otomasyon UI · canlı ekran görüntüleri.
- **Dalga 6 (tamamlandı):** Server-side/CAPI ölçümleme (M7) + KVKK rıza + UI.
- **Dalga 7 (tamamlandı):** Abonelik & faturalama (M10) · CI + sağlamlaştırma · Faturalama UI.
- **Dalga 8 (tamamlandı):** Çoklu hesap / Ajans / white-label (M8) — workspace yönetimi + üye davet + marka.
- **Dalga 9 (tamamlandı):** Güvenlik denetimi + güvenli sertleştirmeler (18 bulgu; 6 düzeltildi, 12 öneri → `08-security-review.md`).
- **Dalga 10 (tamamlandı) — Farklılaşma başlangıcı:** Rekabet hendeği stratejisi + **AYAZ AI Copilot** (Türkçe, veriye gömülü, tool-use'lu asistan) backend + UI.
- **Dalga 11 (tamamlandı):** Cross-channel bütçe optimizatörü (#2) + hedef takibi & forecasting/pacing (#3).
- **Dalga 12 (tamamlandı):** Copilot v2 (aksiyon araçları) + alarm→kök-neden→tek-tık düzeltme döngüsü (#4).
- **Dalga 13 (tamamlandı):** Doğal-dil rapor/pano oluşturucu (#5) + kreatif performans analizi (#6).
- **Dalga 14 (tamamlandı):** Proaktif AI günlük brifing (#7) — 7 farklılaştırıcının tamamı canlı.
- **Dalga 15 (tamamlandı):** Herkese açık pazarlama/landing sayfası + onboarding boş-durum.
- **Dalga 16 (tamamlandı):** Üretim güvenlik sertleştirme (rate limiting + JWT iptal + webhook imzası).
- **Dalga 17 (tamamlandı):** PWA + mobil-optimize deneyim (yüklenebilir "mobil uygulama").
- **Dalga 18 (tamamlandı):** Frontend↔Backend sözleşme denetimi (14 runtime bug düzeltildi).
- **Dalga 19 (tamamlandı):** Backend doğruluk turu — kritik cross-tenant sızıntı + sağlamlaştırma.
- **Dalga 20 (tamamlandı):** Dönem karşılaştırma + CSV export (dashboard/reklam/kreatif).
- **Dalga 21 (tamamlandı):** Dokümantasyon tazeleme + Playwright E2E smoke suite + CI UUID düzeltmesi (taşınabilir `GUID` tipi).
- **Dalga 22 (tamamlandı):** Hesap & Ayarlar — `/settings` (profil + şifre değiştir + bildirim/dil tercihleri) + ilgili `/auth` endpoint'leri.
- **Dalga 23 (tamamlandı):** Global hata sınırları + zarif yükleniyor/boş/hata durumları + 404; paylaşılan `ErrorBoundary`/`StateViews`; SQLite-uyumlu DB engine.
- **Dalga 24 (tamamlandı):** Dark mode + tema değiştirici (Açık/Koyu/Sistem); CSS token tabanlı tema, FOUC önleyici; canlı demo ile doğrulandı.
- **Dalga 25 (tamamlandı):** Tarih aralığı ön-ayarları (Son 7/30/90 gün, Bu ay, Geçen ay) — dashboard/reklam/kreatif; dashboard aralığı hatırlanır.
- **Dalga 26 (tamamlandı):** Uygulama-içi bildirim merkezi — `Notification` modeli + `/notifications` API + nav'da zil/rozet/panel (içgörülerden tembel üretim).
- **Dalga 27 (tamamlandı):** Komut paleti (⌘K/Ctrl+K) — tüm sayfalara hızlı geçiş + komutlar; klavye-öncelikli, erişilebilir.
- **Dalga 28 (tamamlandı):** En Çok Değişenler analizi (`/dashboard/top-movers`) + test-izolasyon düzeltmesi (autouse override temizleyici → flaky testler giderildi).
- **Dalga 29 (tamamlandı):** Türkçe diakritik tutarlılığı — UI metinlerinde eksik Türkçe karakterler düzeltildi (TR-first kalite).
- **Dalga 30 (tamamlandı):** Copilot `get_top_movers` aracı + sıralama mantığının ortak servise (`metrics.compute_top_movers`) çıkarılması.
- **Dalga 31 (tamamlandı):** Yeni içgörü dedektörleri — dönüşüm oranı düşüşü + olumlu hareket (M4: 6 → 8 dedektör).
- **Dalga 32 (tamamlandı):** Başlangıç rehberi (onboarding kontrol listesi) — dashboard'da aktivasyon adımları.
- **Dalga 33 (tamamlandı):** Copilot araç genişlemesi — `get_notifications` + `get_goal_progress` (flagship güçlendirme).
- **Dalga 34 (tamamlandı):** E2E regresyon turu — dashboard hidrasyon hatası (localStorage-in-render) düzeltildi; smoke suite 18/18 yeşil.
- **Dalga 35 (tamamlandı):** Bildirimler tam sayfası (`/notifications`) — filtreler + tümünü okundu; zil + komut paletinden erişim. Smoke 19/19.
- **Dalga 36 (tamamlandı):** Kimlik/güvenlik sertleştirme — şifre değişince oturum geçersizleştirme (iat + credentials_changed_at, migration 0015), timezone doğrulama, Copilot hata-mesajı sızıntısı kapatma.
- **Dalga 37 (tamamlandı):** Şifre değişiminde otomatik yeniden giriş UX'i (Dalga 36 tamamlayıcısı).
- **Dalga 38 (tamamlandı):** Erişilebilirlik — global focus-visible + prefers-reduced-motion.
- **Dalga 39 (tamamlandı):** Frontend birim test altyapısı (Vitest+RTL, 49 test) + CI işi.
- **Dalga 40 (tamamlandı):** Gözlemlenebilirlik — request-ID + yapılandırılmış istek logu + `/health/ready` DB hazırlık probu.
- **Dalga 41 (tamamlandı):** E2E smoke suite CI'da (SQLite tabanlı `e2e-smoke` işi, 19 rota) + smoke chromium-yolu CI-uyumu.
- **Dalga 42 (tamamlandı):** Self-serve kayıt akışı (`/signup`) — kırık PLG kapısı düzeltildi (rakip-analiz bulgusu).
- **Dalga 43 (tamamlandı):** Feed Kural Stüdyosu backend — pause + etki önizleme + dry-run simülasyon + kural-linter (Channable panel ilhamı).
- **Dalga 44 (tamamlandı):** Feed Kural Stüdyosu görsel editör — duraklat + 'Etkiyi Hesapla' barı + kaydetmeden Önizle + linter çipleri (panel kareleri referansıyla).
- **Dalga 45 (tamamlandı):** Türkçe doğal dil → feed kuralı backend (`/rules/from-text`) — cümleden taslak kural + açıklama + etki (Claude+mock).
- **Dalga 46 (tamamlandı):** İçgörü geri-bildirim döngüsü backend — 'Uygulandı' + 👍/👎 (Insight.applied_at/reaction, migration 0017) (Adin kartı ilhamı).
- **Dalga 47 (tamamlandı):** Performans skorlama katmanı backend (`/dashboard/scores`) — şeffaf, kendi-geçmişine-göre 0–100 skorlar (Adin gösterge ilhamı).
- **Dalga 48 (tamamlandı):** Feed Kalite Kapısı backend (`/feeds/.../quality`) — yayın-öncesi zorunlu alan doğrulama + kalite skoru (Channable boşluğu).
- **Dalga 49 (tamamlandı, frontend dahil):** AI ürün-zenginleştirme — kaynakta öneri tablosu + onaylı uygulama.
- **Dalga 50 (tamamlandı):** Omnipresent 'Veriye Sor' — nav + ⌘K'dan Copilot hızlı-sor modalı + asistan derin-link (Adin 'Ask your data' ilhamı, açık + TR).
- **Dalga 51 (tamamlandı):** Deploy hazırlığı — prod Dockerfile'lar + docker-compose.prod + Render blueprint + deploy rehberi (canlı link için turnkey).
- **Dalga 52 (tamamlandı):** M7 Ölçümleme sağlık & olay istatistikleri backend (`/tracking/sources/.../stats`) — iletim sağlığı + olay-bazlı sayım/trend + debug filtreleri (SignalSight panel ilhamı).
- **Dalga 53 (tamamlandı):** M7 olay-bazlı aç/kapa (`event-config`) — kapalı olay CAPI'ye iletilmez (disabled status, migration 0018); SignalSight Event Configuration toggle.
- **Dalga 54 (tamamlandı):** M7 Consent Mode v2 — granular KVKK rıza (4 sinyal) + hedef-bazlı zorunlu sinyaller + cookie-değişkeni snippet + GA4 GCS (migration 0019); SignalSight Cookie Consent ilhamı.
- **Dalga 55 (tamamlandı):** M7 Eşleşme Kalitesi (Event Match Quality) — ham payload'tan ağırlıklı 0-100 skor + tier + sinyal kapsama (migration 0020); `external_id` hash + `fbc`/`fbp` passthrough; KVKK için yalnızca alan-varlığı saklanır. Eşleşme Kalitesi paneli + iyileştirme önerileri. **M7 ölçümleme stüdyosu tamamlandı.**
- **Dalga 56 (tamamlandı):** **M11 İçerik Planlayıcı** (RADAAR-esinli) — organik sosyal içerik takvimi/composer + onay akışı (taslak→onay→zamanlama) + AI açıklama/hashtag önerisi (migration 0021, 11 endpoint, 6 kanal). Canlı yayın bilinçli kimlik-kilitli (501). `/content` kanban panosu. AYAZ artık **ücretli + ölçümleme + organik** üçlüsünü tek açık-metrikli kokpitte topluyor.
- **Dalga 57 (tamamlandı):** **Kreatif → İçerik köprüsü** (M6→M11) — en iyi reklam kreatifini tek tıkla organik içerik taslağına çevir (`POST /content/from-creative`; platform→kanal eşleme + AI altyazı uyarlama). Ücretli içgörü → organik içerik döngüsü; AYAZ'a özgü farklılaştırıcı. İçerik Planlayıcı'da "Kreatiften Oluştur" seçici.
- **Dalga 58 (tamamlandı):** İçerik Takvimi — İçerik Planlayıcı'ya aylık takvim görünümü (Pano/Takvim anahtarı, durum-renkli çipler). RADAAR imza özelliği.
- **Dalga 59 (tamamlandı):** Copilot İçerik Planlayıcı farkındalığı — `get_content_status` aracı; "kaç içerik onay bekliyor?" doğal dille yanıtlanır. Birleşik kokpit + Copilot vaadini derinleştirir.
- **Dalga 60 (tamamlandı):** M7 Dayanıklılık — hata sınıflandırma (kalıcı/geçici/retryable) + `POST /tracking/events/{id}/retry` + `retry_count` (migration 0022) + stats deliverability bloğu; Olay Günlüğü'nde kategori rozeti + Yeniden Gönder. Son SignalSight maddesi; M7 ölçümleme stüdyosu tamamlandı.
- **Dalga 61 (tamamlandı):** **M12 Aylık Bütçe Planlayıcı** — toplam bütçe → hedefe göre (ROAS/dönüşüm/dengeli) platform+kampanya alokasyonu + projeksiyon (migration 0023, 7 endpoint, %5 taban/%60 tavan iteratif koruma). `/planning` sayfası canlı önizleme + kayıtlı planlar. Planlama personasının çekirdek ihtiyacı. Ekip persona yol haritası: `13-team-personas-roadmap.md`.
- **Dalga 62 (tamamlandı):** **M13 Sosyal Gelen Kutusu** (Müşteri Hizmetleri / RADAAR paritesi) — çok kanallı DM/yorum/bahsetme gelen kutusu + panelden yanıt + atama/durum/etiket + duygu analizi + AI yanıt önerisi (migration 0024, 10 endpoint). `/inbox` iki-panelli arayüz. Canlı senkron/gönderim kimlik-kilitli. CS personasının çekirdek ihtiyacı.
- **Dalga 63 (tamamlandı):** **Yönetici (CMO) Görünümü** — `GET /executive/overview` ile KPI + MoM delta + kanal ROI + hedefler + kritik içgörüler + doğal-dil manşet (yeni tablo yok; mevcut servisler). `/executive` tek-ekran üst-düzey özet. CEO/CMO personasının çekirdek ihtiyacı. **Persona yol haritası 3/5: Bütçe + Inbox + CMO görünümü tamam.**
- **Dalga 64 (tamamlandı):** **Copilot çapraz-modül farkındalığı** — `get_budget_status` + `get_inbox_summary` + `get_executive_summary` araçları; her persona bütçe/inbox/yönetici özetini tek Copilot'tan doğal dille sorgular. Birleşik kokpit + tek asistan vaadi tüm yeni modüllerde tam.
- **Dalga 65 (tamamlandı):** **Marcom Kreatif Lensi** — `GET /marcom/creative-insights` (mevcut `ad_performance` reuse); kreatif performansı etkileşim/trafik diliyle + sade içgörü + "Organik içeriğe çevir" köprüsü. `/creative-lens` sayfası. **Persona seti tamam: Performans + Planlama + CS + CMO + Marcom, hepsi tek panel + tek Copilot.**
- **Dalga 66 (tamamlandı):** **Bütçe Plan vs Gerçekleşen** (planlama faz-2) — `GET /budget/plans/{id}/actuals`; kanal-bazlı planlanan vs gerçekleşen + tempo + sapma + harcama/süre temposu değerlendirmesi. `/planning`'de "Gerçekleşen" paneli. Planlama döngüsü kapandı.

### Farklılaştırma Fazı (Dalga 67+) — `14-differentiation-backlog.md`
- **Dalga 67 (tamamlandı):** **Komuta Merkezi** (`/command-center`) — tüm modüllerden "dikkat gerektirenler" akışı + KPI + modül durum kartları; "tek panel" vitrini, ilk nav öğesi. `GET /command-center/overview`.
- **Dalga 68 (tamamlandı):** **Hesap Sağlık Taraması** (`/audit`) — `GET /audit/run`; 6 kategori 16+ kontrol → 0-100 puan + kategorize bulgu + çözüm önerisi. "Tek tıkla ücretsiz denetim" farklılaştırıcısı.
- **Dalga 70 (tamamlandı):** **Sektör Kıyaslama** (`/benchmark`) — `GET /benchmark/overview`; 5 metrik TR e-ticaret referans aralıklarına göre konum (güçlü/ortalama/zayıf) + kanal kıyası. Pazarlama farklılaştırıcısı.
- **Dalga 71 (tamamlandı):** **Proaktif Öneri Merkezi + AI Haftalık Strateji** (`/recommendations`) — `GET /recommendations/feed`, `GET /recommendations/weekly-strategy`, `POST /recommendations/{key}/action`; denetim/bütçe/kıyaslama/hedef/gelen kutusu/içerik sinyallerini tek aksiyon akışında birleştirir + kabul/ertele/reddet iş akışı (kalıcı `recommendation_states`). "Birleşik zeka" katmanı.
- **Dalga 72 (tamamlandı):** **KVKK Rıza Yönetim Merkezi** (`/consent`) — `GET /consent/center`; mevcut ölçümleme/rıza altyapısını sentezler: rıza oranı + Consent Mode v2 granüler sinyal kırılımı + hedef-noktası rıza duruşu + KVKK uyum skoru/kontrol listesi + rıza denetim izi. TR-first uyum farklılaştırıcısı (yeni tablo yok).
- **Dalga 73 (tamamlandı):** **AI Reklam Metni Stüdyosu** (`/ad-studio`) — `POST /ad-studio/generate` + taslak CRUD (`/ad-studio/drafts`); brief'ten Google/Meta/TikTok'a özel reklam metni üretir (şablon + opsiyonel Claude), karakter sınırı doğrulamalı, taslak kütüphaneli. Marcom/kreatif farklılaştırıcısı (`ad_copy_drafts` tablosu).
- **Dalga 69 (tamamlandı):** **Kurulum Sihirbazı** (`/onboarding`) — `GET /onboarding/status`; 5 adımı mevcut veriden otomatik tespit + CTA yönlendirme + ilerleme. Satılabilirlik (yeni kurumsal müşteri hızlı kurulum).
- **Mobil uygulama:** PWA ile yüklenebilir deneyim sağlandı (Dalga 17); native uygulama talebe bağlı.

> **M1–M10 çekirdek modüllerin tamamı + 7 farklılaştırıcı + güvenlik denetimi/sertleştirme + PWA tamamlandı.**
> Tam yapım geçmişi: `CHANGELOG.md`. Özellik kataloğu (modül × endpoint × sayfa): `10-features.md`.

## Farklılaşma Hedefleri (rakipleri geçmek için)
Rakipler stack'in tek katmanını satıyor; AYAZ hepsini birleştirdi. İlerleme:
1. ✅ **AI Copilot** — birleşik veriye gömülü Türkçe asistan (Dalga 10) + **aksiyon araçları** (Dalga 12).
2. ✅ **Cross-channel bütçe optimizasyonu** — bütçe dağıtım önerisi + projeksiyon (Dalga 11).
3. ✅ **Hedef takibi + forecasting/pacing** (Dalga 11).
4. ✅ **Alarm→kök-neden→tek-tık düzeltme** döngüsü (Dalga 12).
5. ✅ **Doğal dilde rapor/pano oluşturucu** — "Meta vs Google son 30 gün" → panoyu kursun (Dalga 13).
6. ✅ **Kreatif performans analizi** — hangi reklam tutuyor + AI yorumu (Dalga 13).
7. ✅ **Proaktif AI günlük brifing** — dün ne oldu / neye dikkat / ne yap (Dalga 14).
8. ⬜ **Atıf / Marketing Mix (hafif)** + benchmark/cohort — kritik kütle + gerçek veri sonrası (stratejist ertelemesi).

> Otonom farklılaşma fazı **tamamlandı**: 7 farklılaştırıcı canlı. Kalan #8 gerçek müşteri verisi
> gerektirir; geri kalan ilerleme artık kullanıcı girdisine bağlı (canlı kimlikler, mobil, öncelik).

> Sıralama değer/risk'e göre ekip tarafından güncellenebilir. Her dalga: tasarla → uzman ajanlarla yap → entegre et → test/doğrula → commit + push.
