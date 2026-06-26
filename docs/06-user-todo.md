# Senin Yapman Gerekenler (en sona bırakıldı)

> Ekip otonom ilerliyor; aşağıdakiler **yalnızca senin yapabileceğin**, projeyi
> bloklamayan işler. Fixture/mock ile geliştirmeye devam ediyoruz; sen bunları
> sağladıkça ilgili modülü "canlı"ya alırız. Hiçbiri ilerlemeyi durdurmuyor.

## 1. Platform API kimlik bilgileri (canlı veri için)
Her reklam/analitik platformunda bir geliştirici uygulaması açıp şunları ver:

| Platform | Gereken |
|---|---|
| Google Ads | OAuth client id/secret · **developer token** · refresh token · customer_id |
| Meta (Facebook/Instagram) | App id/secret · long-lived/system user token · ad_account_id |
| GA4 | OAuth client id/secret · refresh token · property_id |
| Google Search Console | OAuth client id/secret · refresh token · site URL |
| TikTok Ads | App id/secret · access token · advertiser_id |
| (sonra) LinkedIn, Microsoft, Criteo, Pinterest | benzer OAuth/app bilgileri |

> Bunları güvenli şekilde ileteceğin akışı (Vault) ekip kuruyor; sen sadece
> uygulama oluşturup değerleri vereceksin.

## 2. Ödeme & abonelik (M10 zamanı)
- iyzico ticari hesabı (TR tahsilat) · Stripe hesabı (global).
- Plan fiyatlarının nihai onayı.

## 3. Altyapı & alan adı
- Üretim için bulut/hosting tercihi ve bütçe (KVKK için TR/EU bölgesi).
- Alan adı (örn. ayaz.app / .com.tr) ve DNS.
- E-posta gönderimi için bir sağlayıcı (SendGrid/Postmark/Amazon SES) hesabı.
  - Not: Kullanıcı bildirim tercihleri (**Ayarlar → Tercihler**: `email_alerts`,
    `email_briefing`) zaten kaydediliyor; SMTP bağlanınca uyarı/brifing dağıtımı
    bu tercihlere göre filtrelenecek (şu an dağıtım stub — yalnızca loglar).
- (M4 için) Anthropic API anahtarı — Türkçe içgörü üretimi için (ekip mock ile geliştirir).

## 4. İçerik & marka
- Logo, marka renkleri, ürün adı kesinleşmesi (kod adı şu an AYAZ).
- Pazarlama/landing metinleri (gerekirse ekip taslak üretir).

## 5. Hukuki / uyum
- KVKK aydınlatma metni & gizlilik politikası onayı.
- Alt-işleyici (sub-processor) sözleşmeleri (platformlar, hosting).

## 6. Canlıya geçiş öncesi güvenlik (Dalga 9 denetiminden)
Detaylar: `08-security-review.md`. Bunlar **canlı kullanım/ödeme öncesi** şart, geliştirmeyi bloklamıyor.

Dalga 16'da tamamlananlar (artık kodda hazır):
- ✅ **Rate limiting** — `auth/login`, `auth/signup`, `auth/change-password`, `tracking/collect`, `feeds/public`, `reports/public`.
- ✅ **JWT iptal** — çıkışta/üyelik değişince token deny-list (`revoked_tokens`).
- ✅ **Faturalama webhook imza doğrulaması** — Stripe-Signature / iyzico HMAC doğrulama kodu hazır (canlıda gerçek secret ile etkinleşir).

Senden hâlâ beklenen / canlı öncesi yapılacaklar:
- **SSRF koruması:** feed `source_url` çekiminde iç ağ koruması (öneri aşamasında).
- **Postgres RLS:** tenant izolasyonunu uygulama + veritabanı katmanında ikiye katlama.
- **Üretim env:** `JWT_SECRET`, `VAULT_KEY` güçlü değerlerle (kod artık production'da default'ları reddediyor), TR/EU bölgede barındırma.

---
**Şimdilik senden hiçbir şey beklenmiyor.** Bu liste sen müsait olduğunda, sırasıyla
ele alınacak; ekip bu sırada fixture/mock ile tüm modülleri geliştirmeye devam ediyor.
