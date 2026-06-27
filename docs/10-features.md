# AYAZ — Özellik Kataloğu (Feature Catalog)

> Her modülün ne yaptığı + **gerçek** API endpoint'leri (`backend/ayaz/api/v1/`) +
> ilgili web sayfası (`frontend/src/app/`). Tüm v1 endpoint'leri `/api/v1` önekiyle servis
> edilir (`backend/ayaz/main.py`). Sayfalar Next.js route segmentleridir.
>
> Toplam: **19 router · ~123 endpoint · 19 web sayfası · 10 konektör.**
> Durum etiketleri: 🟢 canlı (kod + fixture/mock) · 🟡 kısmi · ⏳ canlı kimlik bekler.

---

## Özet tablo (modül → sayfa → ana endpoint kümesi)

| Modül | Web sayfası | API öneki | Durum |
|---|---|---|---|
| M1 Bağlantı Hub'ı | `/connections` | `/connectors`, `/oauth` | 🟢 / ⏳ canlı veri |
| M2 Birleşik Veri + Metrik | (dashboard içinde) | `/dashboard` | 🟢 |
| M3 Dashboard & Raporlama | `/dashboard`, `/reports` | `/dashboard`, `/reports` | 🟢 |
| M4 AI İçgörü & Uyarı | `/insights` | `/insights` | 🟢 |
| M5 Feed Yönetimi | `/feeds` | `/feeds` | 🟢 |
| M6 Reklam Yönetimi | `/ads` | `/ads` | 🟢 okuma/öneri |
| M7 Server-side / CAPI | `/tracking` | `/tracking` | 🟢 |
| M8 Çoklu Hesap / Ajans | `/workspaces` | `/workspaces` | 🟢 |
| M9 Otomasyon & Kurallar | `/automation` | `/automation` | 🟢 |
| M10 Abonelik & Faturalama | `/billing` | `/billing` | 🟢 / ⏳ canlı ödeme |
| Platform — Kimlik | `/login` | `/auth` | 🟢 |
| Platform — Hesap & Ayarlar | `/settings` | `/auth/me`, `/auth/preferences` | 🟢 |
| Bildirim Merkezi | (nav zili) | `/notifications` | 🟢 |
| En Çok Değişenler | (dashboard) | `/dashboard/top-movers` | 🟢 |
| #1 AI Copilot | `/assistant` | `/assistant` | 🟢 |
| #2 Bütçe Optimizatörü | `/optimizer` | `/optimizer` | 🟢 |
| #3 Hedef & Forecasting | `/goals` | `/goals` | 🟢 |
| #4 Alarm→Düzeltme | `/insights` (fix akışı) | `/insights/{id}/fixes` | 🟢 |
| #5 NL Rapor Oluşturucu | `/report-builder` | `/reports/build` | 🟢 |
| #6 Kreatif Analizi | `/creatives` | `/creatives` | 🟢 |
| #7 Proaktif Brifing | `/briefing` | `/briefings` | 🟢 |
| Pazarlama / Landing | `/` (home) | — | 🟢 |

---

## Platform — Kimlik & Sağlık

**Ne:** Kayıt/giriş, JWT oturumu, tenant context. Multi-tenant izolasyon her sorguda
`tenant_id` filtresi ile uygulanır.

**Sayfa:** `/login` · **Servis:** `services/auth.py` (bcrypt + JWT)

| Method | Path | Açıklama |
|---|---|---|
| POST | `/api/v1/auth/signup` | Yeni kullanıcı + tenant oluştur |
| POST | `/api/v1/auth/login` | Giriş → JWT |
| GET | `/api/v1/auth/me` | Mevcut kullanıcı (profil) |
| PATCH | `/api/v1/auth/me` | Profili güncelle (ad/e-posta) |
| POST | `/api/v1/auth/change-password` | Şifre değiştir (rate-limited) |
| GET | `/api/v1/auth/preferences` | Bildirim/dil tercihleri |
| PATCH | `/api/v1/auth/preferences` | Tercihleri güncelle |
| POST | `/api/v1/auth/logout` | Çıkış (token iptali) |
| GET | `/health` | Liveness probe (versiyonsuz) |

**Hesap & Ayarlar sayfası:** `/settings` — Profil · Şifre Değiştir · Tercihler
(dil `tr`/`en`, saat dilimi, `email_alerts`, `email_briefing`).

---

## M1 — Bağlantı Hub'ı (Connectors + OAuth Broker)

**Ne:** 10 platform konektörü tek tip `Connector` sözleşmesini uygular. OAuth Broker
token saklama/yenilemeyi merkezden yönetir; sırlar Vault'tan okunur.
**Konektörler:** Google Ads, Meta Ads, GA4, Search Console, TikTok Ads, LinkedIn Ads,
Microsoft/Bing Ads, Criteo, Pinterest Ads, Meta CAPI (+ fixture tabanlı `sample`).

**Sayfa:** `/connections` · **Servis:** `connectors/`, `services/oauth_broker.py`, `services/vault.py`, `services/sync.py`

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/v1/connectors/` | Mevcut konektör tipleri (registry) |
| GET | `/api/v1/connectors/accounts` | Bağlı hesaplar + sync durumu |
| POST | `/api/v1/connectors/accounts` | Yeni hesap bağla |
| GET | `/api/v1/connectors/accounts/{account_id}` | Hesap detayı |
| DELETE | `/api/v1/connectors/accounts/{account_id}` | Hesap bağlantısını kaldır |
| GET | `/api/v1/oauth/{platform}/authorize` | OAuth consent başlat |
| GET | `/api/v1/oauth/{platform}/callback` | OAuth callback → token Vault'a |

> ⏳ Canlı veri için her platformda uygulama/kimlik gerekir (`docs/06-user-todo.md`).

---

## M2 — Birleşik Veri + Metrik Katmanı

**Ne:** Normalize tek doğruluk kaynağı (star schema fact/dim). Türetilmiş metrikler
(CTR/CPC/CPA/ROAS) Metric Layer'da tek tanımdan üretilir, fact'te materyalize edilmez.
Para birimi tenant raporlama para birimine, zaman UTC'ye normalize.

**Sayfa:** dashboard içinde tüketilir · **Servis:** `services/metrics.py` · **Modeller:** `models/analytics.py`

(Doğrudan endpoint yoktur; M3 dashboard ve diğer tüm modüller bu katmanı okur.)

---

## M3 — Dashboard & Raporlama

**Ne:** Kanal-üstü özet + zaman serisi; **dönem karşılaştırma** ve **CSV export** (Dalga 20).
Raporlama: özelleştirilebilir rapor tanımları, zamanlı/paylaşılabilir **white-label** müşteri raporu (public token ile).

**Sayfalar:** `/dashboard`, `/reports` · **Servis:** `services/reports.py` · **Modeller:** `models/reports.py`

Dashboard:

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/v1/dashboard/summary` | Kanal-üstü özet KPI'lar (+ dönem karşılaştırma) |
| GET | `/api/v1/dashboard/timeseries` | Zaman serisi metrikleri |
| GET | `/api/v1/dashboard/export` | CSV export |

Raporlama (router öneki `/reports`):

| Method | Path | Açıklama |
|---|---|---|
| GET / POST | `/api/v1/reports/definitions` | Rapor tanımlarını listele / oluştur |
| GET / PATCH / DELETE | `/api/v1/reports/definitions/{id}` | Tanım detay / güncelle / sil |
| GET | `/api/v1/reports/definitions/{id}/preview` | Önizleme |
| POST | `/api/v1/reports/definitions/{id}/share` | Paylaşım linki oluştur |
| GET / POST | `/api/v1/reports/schedules` | Zamanlamaları listele / oluştur |
| GET / PATCH / DELETE | `/api/v1/reports/schedules/{id}` | Zamanlama detay / güncelle / sil |
| GET | `/api/v1/reports/shares` | Aktif paylaşımlar |
| DELETE | `/api/v1/reports/shares/{share_id}` | Paylaşımı iptal et |
| GET | `/api/v1/reports/public/{public_token}` | White-label public rapor (auth'suz) |

---

## M4 — AI İçgörü & Uyarı

**Ne:** 8 anomali dedektörü (roas_drop, spend_spike, zero_conversions, ctr_drop,
cpc_rise, anomaly + **cvr_drop**, **positive_movement** — olumlu "kazanım" içgörüsü)
+ Türkçe doğal-dil narrator + uyarı kuralları (e-posta/Slack) + uygulama-içi **bildirim
merkezi** (`/notifications`: liste, okunmamış sayısı, okundu işaretle). Ayrıca
farklılaştırıcı #4 (alarm→kök-neden→tek-tık düzeltme) buradaki fix endpoint'leriyle akar.

**Sayfa:** `/insights` · **Servis:** `services/insights.py`, `services/narrator.py`, `services/fixes.py`, `services/notifications.py` · **Modeller:** `models/insights.py`

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/v1/insights` | İçgörüleri listele |
| PATCH | `/api/v1/insights/{insight_id}` | İçgörü durumunu güncelle (ör. okundu/kapat) |
| POST | `/api/v1/insights/generate` | İçgörü üretimini tetikle |
| GET / POST | `/api/v1/insights/alert-rules` | Uyarı kurallarını listele / oluştur |
| GET / PATCH / DELETE | `/api/v1/insights/alert-rules/{rule_id}` | Kural detay / güncelle / sil |
| GET | `/api/v1/insights/{insight_id}/fixes` | (#4) Kök-neden + önerilen düzeltmeler |
| POST | `/api/v1/insights/{insight_id}/fixes/apply` | (#4) Tek-tık düzeltme uygula (kural taslağı) |

---

## M5 — Feed Yönetimi

**Ne:** Tek kaynak feed → kurallarla kanal-özel çıktı; her kanal için ayrı **public feed URL'i**
(Google Shopping, Meta katalog vb.). Kaynak → kanal → kural hiyerarşisi.

**Sayfa:** `/feeds` · **Servis:** `services/feeds.py` · **Modeller:** `models/feeds.py`

| Method | Path | Açıklama |
|---|---|---|
| GET / POST | `/api/v1/feeds/sources` | Feed kaynaklarını listele / oluştur |
| GET / PATCH / DELETE | `/api/v1/feeds/sources/{source_id}` | Kaynak detay / güncelle / sil |
| POST | `/api/v1/feeds/sources/{source_id}/sync` | Kaynağı yeniden çek |
| GET / POST | `/api/v1/feeds/sources/{source_id}/channels` | Kanalları listele / oluştur |
| GET / PATCH / DELETE | `/api/v1/feeds/channels/{channel_id}` | Kanal detay / güncelle / sil |
| GET / POST | `/api/v1/feeds/channels/{channel_id}/rules` | Dönüşüm kurallarını listele / ekle |
| POST | `/api/v1/feeds/channels/{channel_id}/rules/reorder` | Kural sırasını değiştir |
| PATCH / DELETE | `/api/v1/feeds/rules/{rule_id}` | Kural güncelle / sil |
| GET | `/api/v1/feeds/public/{public_token}` | Kanal-özel public feed çıktısı (auth'suz) |

---

## M6 — Reklam Yönetimi & Optimizasyon

**Ne:** Kanal-üstü kampanya görünümü + optimizasyon önerisi. Şu an **okuma + öneri**
(dedektörler kampanya granülünde yeniden kullanılır); doğrudan platforma **yazma faz 2**.
Dönem karşılaştırma + CSV export (Dalga 20) destekli.

**Sayfa:** `/ads` · **Servis:** `services/ads.py`

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/v1/ads/campaigns` | Kanal-üstü kampanya listesi |
| GET | `/api/v1/ads/campaigns/export` | Kampanya CSV export |
| GET | `/api/v1/ads/campaigns/{campaign_id}` | Kampanya detayı |
| GET | `/api/v1/ads/recommendations` | Optimizasyon önerileri |
| POST | `/api/v1/ads/campaigns/{campaign_id}/actions` | Kampanya aksiyonu (öneri/taslak; yazma faz 2) |

---

## M7 — Server-side Ölçümleme (CAPI)

**Ne:** Toplama (collect) endpoint'i + hash/consent/dedup + 3 platforma iletim
(Meta CAPI, TikTok Events, GA4 Measurement Protocol) + KVKK rızası. Kaynak → hedef (destination) yapısı.

**Sayfa:** `/tracking` · **Servis:** `services/tracking.py` · **Modeller:** `models/tracking.py`

| Method | Path | Açıklama |
|---|---|---|
| GET / POST | `/api/v1/tracking/sources` | Tracking kaynaklarını listele / oluştur |
| GET / PATCH / DELETE | `/api/v1/tracking/sources/{source_id}` | Kaynak detay / güncelle / sil |
| GET | `/api/v1/tracking/sources/{source_id}/snippet` | Kuruluma hazır JS snippet |
| GET | `/api/v1/tracking/sources/{source_id}/events` | Toplanan olaylar |
| GET / POST | `/api/v1/tracking/sources/{source_id}/destinations` | Hedefleri listele / ekle |
| GET / PATCH / DELETE | `/api/v1/tracking/destinations/{dest_id}` | Hedef detay / güncelle / sil |
| POST | `/api/v1/tracking/collect/{public_token}` | Olay toplama (auth'suz public ingest) |

---

## M8 — Çoklu Hesap / Ajans (Workspaces)

**Ne:** Workspace yönetimi, üye davet + roller, white-label marka ayarları, workspace switcher.

**Sayfa:** `/workspaces` · **Servis:** `services/workspaces.py` · **Bileşen:** `components/WorkspaceSwitcher.tsx`

| Method | Path | Açıklama |
|---|---|---|
| GET / POST | `/api/v1/workspaces` | Workspace'leri listele / oluştur |
| POST | `/api/v1/workspaces/switch` | Aktif workspace değiştir |
| GET / PATCH | `/api/v1/workspaces/current` | Aktif workspace detay / güncelle (white-label) |
| GET | `/api/v1/workspaces/members` | Üyeler |
| POST | `/api/v1/workspaces/invitations` | Üye davet et |
| POST | `/api/v1/workspaces/invitations/accept` | Daveti kabul et |
| PATCH / DELETE | `/api/v1/workspaces/members/{membership_id}` | Rol güncelle / üye çıkar |

---

## M9 — Otomasyon & Kurallar

**Ne:** "ROAS < x ise kampanyayı durdur" tarzı kural motoru + audit log + zamanlı çalıştırma (Celery beat).

**Sayfa:** `/automation` · **Servis:** `services/automation.py` · **Modeller:** `models/automation.py`

| Method | Path | Açıklama |
|---|---|---|
| GET / POST | `/api/v1/automation/rules` | Kuralları listele / oluştur |
| GET / PATCH / DELETE | `/api/v1/automation/rules/{rule_id}` | Kural detay / güncelle / sil |
| POST | `/api/v1/automation/rules/{rule_id}/run` | Kuralı elle çalıştır |
| GET | `/api/v1/automation/rules/{rule_id}/runs` | Çalıştırma geçmişi (audit) |

---

## M10 — Abonelik & Faturalama

**Ne:** Planlar, entitlement/gating, kullanım; iyzico (TR) + Stripe (global) sağlayıcı.
Sağlayıcı stub canlı; gerçek tahsilat ve webhook imza doğrulaması müşteri kimliği bekler.

**Sayfa:** `/billing` · **Servis:** `services/billing.py` · **Modeller:** `models/billing.py`

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/v1/billing/plans` | Mevcut planlar |
| GET | `/api/v1/billing/subscription` | Aktif abonelik + entitlement |
| POST | `/api/v1/billing/checkout` | Ödeme/abonelik başlat |
| POST | `/api/v1/billing/cancel` | Abonelik iptal |
| POST | `/api/v1/billing/webhook/{provider}` | Sağlayıcı webhook (Stripe/iyzico) |

> ⏳ Gerçek ödeme için iyzico/Stripe hesabı + webhook imza doğrulaması (go-live zorunlu).

---

## Farklılaştırıcı #1 — AYAZ AI Copilot

**Ne:** Birleşik veri üstünde Türkçe konuşan, kaynak-gösterimli, **tool-use'lu** asistan.
Sohbet oturumu/geçmiş tutar; modül servis fonksiyonlarını tool olarak çağırır
(metrik sorgula, içgörü listele, kampanya performansı, rapor kur, kural taslakla). v2 ile
aksiyon araçları eklendi. Halüsinasyona karşı zorunlu veri-alıntısı + "uydurma" guardrail.

**Sayfa:** `/assistant` · **Servis:** `services/copilot.py`, `services/copilot_tools.py`, `services/narrator.py` · **Modeller:** `models/copilot.py` · **API öneki:** `/assistant`

| Method | Path | Açıklama |
|---|---|---|
| GET / POST | `/api/v1/assistant/conversations` | Sohbetleri listele / başlat |
| GET | `/api/v1/assistant/conversations/{conversation_id}/messages` | Sohbet mesajları |
| POST | `/api/v1/assistant/conversations/{conversation_id}/messages` | Mesaj gönder (tool-use + grounded yanıt) |

---

## Farklılaştırıcı #2 — Cross-channel Bütçe Optimizatörü

**Ne:** Kanal-üstü mevcut bütçeyi yeniden dağıtım önerisi ("Meta'dan ₺X'i Google'a kaydır →
tahmini +%Y dönüşüm / +Z ROAS"), marjinal-ROAS mantığı + tahmini-etki bandı. Salt öneri (düşük risk).

**Sayfa:** `/optimizer` · **Servis:** `services/optimizer.py`

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/v1/optimizer/budget` | Kanal-üstü bütçe yeniden-dağıtım önerisi + projeksiyon |

---

## Farklılaştırıcı #3 — Hedef Takibi + Forecasting/Pacing

**Ne:** Hedef koy (dönüşüm/gelir), AYAZ ulaşır mı tahmin eder (pacing + projeksiyon),
"yetişmek için günlük ne gerekir" der, sapınca uyarır.

**Sayfa:** `/goals` · **Servis:** `services/goals.py` · **Modeller:** `models/goals.py`

| Method | Path | Açıklama |
|---|---|---|
| GET / POST | `/api/v1/goals` | Hedefleri listele / oluştur |
| GET / PATCH / DELETE | `/api/v1/goals/{goal_id}` | Hedef detay / güncelle / sil |
| GET | `/api/v1/goals/{goal_id}/progress` | İlerleme + pacing/forecast + "yetişme olasılığı" |

---

## Farklılaştırıcı #4 — Alarm → Kök-Neden → Tek-Tık Düzeltme

**Ne:** M4 içgörüsü/alarmı bir adım derinleşir: hangi entity tetikledi (drill-down) →
önerilen kural taslağı → tek-tık uygula (M4→M6→M9 zinciri). Otomatik yürütme opt-in.

**Sayfa:** `/insights` (fix akışı) · **Servis:** `services/fixes.py`
**Endpoint'ler:** M4'teki `GET /api/v1/insights/{insight_id}/fixes` ve
`POST /api/v1/insights/{insight_id}/fixes/apply`.

---

## Farklılaştırıcı #5 — Doğal Dilde Rapor/Pano Oluşturucu

**Ne:** "Meta vs Google son 30 gün ROAS ve harcama" → yapılandırılmış pano/rapor taslağı.
NL → dashboard config. Copilot'un da çağırabildiği bir aksiyon-tool'u.

**Sayfa:** `/report-builder` · **Servis:** `services/report_builder.py` · **API öneki:** `/reports`

| Method | Path | Açıklama |
|---|---|---|
| POST | `/api/v1/reports/build` | Doğal dilden rapor/pano taslağı üret |

---

## Farklılaştırıcı #6 — Kreatif Performans Analizi

**Ne:** Ad/kreatif seviyesinde performans sıralaması + fatigue (yorgunluk) tespiti + AI yorumu.
Dönem karşılaştırma + CSV export (Dalga 20) destekli.

**Sayfa:** `/creatives` · **Servis:** `services/creatives.py`

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/v1/creatives/performance` | Kreatif performans sıralaması + fatigue |
| GET | `/api/v1/creatives/export` | Kreatif performans CSV export |

---

## Farklılaştırıcı #7 — Proaktif AI Günlük Brifing

**Ne:** Her sabah otomatik özet: "dün ne oldu / neye dikkat / ne yap". Pazartesi-açılışı
alışkanlığı kuran retention kancası ("bu hafta ne kaçırdım?").

**Sayfa:** `/briefing` · **Servis:** `services/briefing.py` · **Modeller:** `models/briefing.py` · **API öneki:** `/briefings`

| Method | Path | Açıklama |
|---|---|---|
| GET | `/api/v1/briefings` | Geçmiş brifingler |
| GET | `/api/v1/briefings/latest` | En güncel brifing |
| POST | `/api/v1/briefings/generate` | Brifing üretimini tetikle |

---

## Pazarlama / Landing & Onboarding

**Ne:** Herkese açık pazarlama/landing sayfası (Dalga 15) + ilk kullanıcı için onboarding
boş-durum deneyimi. Web uygulaması PWA'dır (Dalga 17): `manifest.json` + `sw.js` → yüklenebilir mobil deneyim.

**Sayfa:** `/` (home / landing)

---

## Notlar

- **Auth'suz public endpoint'ler:** `/health`, `/reports/public/{token}`,
  `/feeds/public/{token}`, `/tracking/collect/{token}`, OAuth callback. Diğer her şey JWT + tenant context ister.
- **Swagger/Redoc** yalnızca `DEBUG` modunda açıktır (`/docs`, `/redoc`).
- **Sayım yöntemi:** endpoint'ler `backend/ayaz/api/v1/*.py` içindeki `@router.<method>`
  dekoratörlerinden, sayfalar `frontend/src/app/**/page.tsx` dosyalarından çıkarıldı.
