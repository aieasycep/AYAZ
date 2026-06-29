# AYAZ — Deploy & 10:00 Review Kılavuzu

> Bu kılavuz, ürünü render.com (+ Vercel) üzerinde ayağa kaldırıp arayüzü
> incelemek için gerekenleri ve bu oturumda eklenen yenilikleri özetler.
> Mimari: **backend + Postgres → Render**, **frontend → Vercel**.

## 1. Hızlı deploy (Render — backend + DB)

1. Render Dashboard → **New → Blueprint** → bu repoyu seç. Render `render.yaml`'ı
   okuyup şunları sağlar: `ayaz-db` (Postgres) + `ayaz-backend` (Docker web servisi).
2. İlk deploy sonrası **Environment** sekmesinde şu değişkenleri ayarla:
   - `VAULT_KEY` — 32 byte URL-safe base64 (örn. `python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`).
   - `ALLOWED_ORIGINS` — Vercel frontend URL'in (örn. `https://ayaz.vercel.app`).
   - **`SEED_DEMO=true`** — review/demo deploy'u için. Migration sonrası idempotent
     demo verisini yükler; böylece arayüz boş değil **dolu** görünür. (Gerçek
     production'da boş bırak.)
   - (Opsiyonel) `ANTHROPIC_API_KEY` — AI anlatı/öneri metinleri "yapay zeka"
     kaynaklı üretilir; boşsa her şey deterministik şablonla çalışır.
   - (Opsiyonel) `REDIS_URL` — Celery zamanlı görevler için; boşsa app yine açılır.
3. Pre-deploy komutu otomatik: `alembic upgrade head && python -m scripts.seed_if_enabled`.
   - **Doğrulandı:** tüm migration zinciri (0001→0026) gerçek Postgres 16'da temiz
     uygulanıyor; `SEED_DEMO=true` ile seed Postgres'te sorunsuz çalışıyor; tüm
     ana servisler Postgres'e karşı doğru sonuç veriyor.

## 2. Frontend (Vercel)

1. Vercel → New Project → repo → root `frontend/`.
2. Env: `NEXT_PUBLIC_API_BASE = https://<ayaz-backend>.onrender.com` (build-time).
3. Deploy. (Alternatif: `frontend/Dockerfile` ile başka bir Render web servisi —
   standalone çıktı + statik kopyalama Dockerfile içinde hazır.)

## 3. Demo girişi

- E-posta: `demo@ayaz.app`  ·  Parola: `demo12345`
- Demo tenant zengin veriyle gelir: 45 gün metrik (3 kanal/7 kampanya), feed'ler,
  içgörüler, içerik, bütçe planları, sosyal gelen kutusu, ölçümleme olayları, vb.

## 4. Bu oturumda eklenenler (Dalga 71–79) — neye bakmalı

| Dalga | Özellik | Ekran | Ne gösterir |
|------|---------|-------|-------------|
| 71 | **Öneri Merkezi** | `/recommendations` | Tüm modüllerden tek aksiyon akışı + AI haftalık strateji + kabul/ertele/reddet |
| 72 | **KVKK Rıza Merkezi** | `/consent` | Rıza oranı, Consent Mode v2 sinyalleri, KVKK uyum skoru + denetim izi |
| 73 | **AI Reklam Metni Stüdyosu** | `/ad-studio` | Brief'ten Google/Meta/TikTok reklam metni üretimi + karakter sınırı + taslak kütüphanesi |
| 74 | **Bütçe Senaryo Simülatörü** | `/budget-simulator` | Kanal bütçesini kaydır → tahmini sonuç (ROAS/dönüşüm) anında |
| 75 | **Rol Görünümü** | `/roles` | Her ekip için (Performans/Marcom/Müşteri Hizmetleri/Planlama/Yönetim) özel kokpit |
| 76 | **Dönüşüm Hunisi** | `/funnel` | 5 adımlı müşteri yolculuğu + adım düşüşleri + en büyük düşüş |
| 77 | **Copilot genişletme** | "Veriye Sor" | Huni/KVKK/kıyaslama/denetim sorularını da yanıtlar |
| 78 | **Gruplu Navigasyon** | üst menü | 32 sayfa 7 kategori açılır menüde — hepsi erişilebilir |
| 79 | **Postgres Deploy Düzeltmesi** | (altyapı) | `alembic upgrade head` artık Postgres'te çalışır + opt-in demo seed |

Önceki personalar (Dalga 55–70): Performans paneli, Yönetici görünümü, Sektör
Kıyaslama, Hesap Sağlık Taraması (Denetim), Komuta Merkezi, Kurulum Sihirbazı,
İçerik Planlayıcı, Kreatif Lensi, Sosyal Gelen Kutusu, Aylık Bütçe Planlayıcı.

## 5. Kimlik bekleyen (no-cred) kısımlar

Aşağıdakiler canlı hesap/kimlik gerektirir ve net "kimlik bekliyor" durumundadır;
operatör kimlik bilgisi girince aktifleşir:

- **Canlı OAuth bağlama** (Google Ads/GA4/Search Console/Meta/TikTok) — broker hazır;
  client id/secret operatör tarafından girilince çalışır.
- **Sosyal medya tek-tıkla paylaşım** — yayınlama OAuth'u gerektirir (şu an 501 gate).
- **Faturalama** (Iyzico/Stripe) — anahtarlar girilince.
- **Celery zamanlı görevler** — `REDIS_URL` girilince.

## 6. Revizyon akışı

Arayüze bakıp not aldıkça, her revizyon küçük odaklı bir dalga olarak işlenebilir
(tasarla → uzman ajan → test → ekran görüntüsü → commit). Mevcut kalite çıtası:
backend **2540 test yeşil**, frontend **417 test yeşil**, tsc temiz, build yeşil.
