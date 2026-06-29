# AYAZ — Deploy & Tam Performans Test Kılavuzu ($0)

> Sistemi **tam performansta, $0 maliyetle** test etmek için reçete:
> **frontend → Vercel (free) · backend → Render (free) · veritabanı → Neon (free)**.
> Önerilen ekler: Upstash Redis (free, arka plan işleri) + Anthropic API anahtarı
> (gerçek AI metinleri) + keep-warm ping (cold-start önleme). Hepsi ücretsiz.
> Sistemi tamamen canlıya alırken Render'ı ücretli plana yükseltmek yeterli.

## 0. Sırayla ne yapacaksın (özet)
1. **Neon**'da ücretsiz Postgres oluştur → connection string'i kopyala.
2. **Render**'da Blueprint ile backend'i deploy et → env'leri (DATABASE_URL=Neon,
   VAULT_KEY, ALLOWED_ORIGINS, SEED_DEMO=true) gir.
3. **Vercel**'de frontend'i deploy et → NEXT_PUBLIC_API_BASE = Render backend URL.
4. Render backend URL'ini **ALLOWED_ORIGINS**'a Vercel URL'i olarak ekle (CORS).
5. (Ops.) **UptimeRobot** ile backend `/health`'i 10 dk'da bir pingle → uyku yok.

## 1. Veritabanı — Neon (ücretsiz, uzun ömürlü)

1. https://neon.tech → ücretsiz hesap → **Create project** (bölge: AB / Frankfurt
   önerilir, Türkiye'ye yakın).
2. Proje açılınca **Connection string**'i kopyala. Şuna benzer:
   `postgresql://kullanici:parola@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require`
3. Bu string'i **olduğu gibi** kullan — uygulama `+psycopg` sürücüsünü otomatik
   ekler, `?sslmode=require`'ı korur. Elle değiştirmen gerekmez.

> Not: Render'ın kendi ücretsiz Postgres'i de var ama ~90 günde siliniyor. Neon
> free uzun ömürlü olduğu için test boyunca silinme derdi olmaz.

## 2. Backend — Render (ücretsiz)

1. Render Dashboard → **New → Blueprint** → bu repoyu seç. Render `render.yaml`'ı
   okuyup `ayaz-backend` (Docker web servisi, free) sağlar. (Yönetilen DB YOK —
   Neon kullanıyoruz.)
2. İlk deploy sonrası **Environment** sekmesinde:
   - `DATABASE_URL` — Neon connection string'i (1. adım) yapıştır.
   - `VAULT_KEY` — 32 byte URL-safe base64. Üret: `python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`
   - `ALLOWED_ORIGINS` — Vercel frontend URL'in (örn. `https://ayaz.vercel.app`) — 3. adımdan sonra netleşir, geri gel doldur.
   - **`SEED_DEMO=true`** — zengin demo verisiyle dolu arayüz için.
   - (Ops.) `REDIS_URL` — Upstash Redis free URL (Celery arka plan işleri).
   - (Ops.) `ANTHROPIC_API_KEY` — gerçek AI metinleri (yoksa şablonla çalışır).
3. Migrasyon + seed **servis başlarken** otomatik çalışır
   (`alembic upgrade head && python -m scripts.seed_if_enabled && uvicorn ...`).
   Free planda preDeploy olmadığı için başlangıç komutuna konuldu; idempotenttir.
   - **Doğrulandı:** migration zinciri (0001→0026) gerçek Postgres 16'da temiz
     uygulanıyor; `SEED_DEMO=true` seed'i Postgres'te sorunsuz; tüm ana servisler
     Postgres'e karşı doğru sonuç veriyor.
4. Backend URL'ini not al: `https://ayaz-backend-xxxx.onrender.com`.

## 3. Frontend — Vercel (ücretsiz)

1. https://vercel.com → New Project → bu repo → **Root Directory: `frontend`**.
2. Environment Variable: `NEXT_PUBLIC_API_BASE = https://ayaz-backend-xxxx.onrender.com`
   (build-time'da gömülür; 2. adımdaki Render backend URL'i).
3. Deploy. Vercel URL'ini (örn. `https://ayaz.vercel.app`) Render'daki
   `ALLOWED_ORIGINS`'a yaz (CORS) ve backend'i bir kez yeniden deploy et.

## 4. Cold-start'ı önle (tam performans için, $0)

Render free servis 15 dk hareketsizlikte uyur → ilk istek ~50 sn gecikir (yanlış
"yavaş" izlenimi). Ücretsiz çözüm:
- **UptimeRobot** (veya cron-job.org) → 5–10 dk'da bir `https://<backend>/health`
  adresine HTTP isteği → servis hep uyanık kalır, cold-start olmaz.

> İpucu: İlk deploy'da `SEED_DEMO=true` bırak; demo verisi yüklendikten sonra
> istersen `false` yapabilirsin (her uyanışta seed idempotent çalışır, zaten
> hızlı atlar — bırakman da sorun değil).

## 5. Demo girişi

- E-posta: `demo@ayaz.app`  ·  Parola: `demo12345`
- Demo tenant zengin veriyle gelir: 45 gün metrik (3 kanal/7 kampanya), feed'ler,
  içgörüler, içerik, bütçe planları, sosyal gelen kutusu, ölçümleme olayları, vb.

## 6. Bu oturumda eklenenler (Dalga 71–82) — neye bakmalı

| Dalga | Özellik | Ekran | Ne gösterir |
|------|---------|-------|-------------|
| 71 | **Öneri Merkezi** | `/recommendations` | Tüm modüllerden tek aksiyon akışı + AI haftalık strateji + kabul/ertele/reddet |
| 72 | **KVKK Rıza Merkezi** | `/consent` | Rıza oranı, Consent Mode v2 sinyalleri, KVKK uyum skoru + denetim izi |
| 73 | **AI Reklam Metni Stüdyosu** | `/ad-studio` | Brief'ten Google/Meta/TikTok reklam metni üretimi + karakter sınırı + taslak kütüphanesi |
| 74 | **Bütçe Senaryo Simülatörü** | `/budget-simulator` | Kanal bütçesini kaydır → tahmini sonuç (ROAS/dönüşüm) anında |
| 75 | **Rol Görünümü** | `/roles` | Her ekip için (Performans/Marcom/Müşteri Hizmetleri/Planlama/Yönetim) özel kokpit |
| 76 | **Dönüşüm Hunisi** | `/funnel` | 5 adımlı müşteri yolculuğu + adım düşüşleri + en büyük düşüş |
| 77 | **Copilot genişletme** | "Veriye Sor" | Huni/KVKK/kıyaslama/denetim sorularını da yanıtlar |
| 78 | **Gruplu Navigasyon** | üst menü | 34 sayfa 7 kategori açılır menüde — hepsi erişilebilir |
| 79 | **Postgres Deploy Düzeltmesi** | (altyapı) | `alembic upgrade head` artık Postgres'te çalışır + opt-in demo seed |
| 80 | **Pazarlama Fırsat Takvimi** | `/marketing-calendar` | TR ticari/sezonsal günler (11.11, Efsane Cuma, bayramlar…) + lead-time + hazırlık durumu |
| 81 | **Komuta Merkezi zenginleştirme** | `/command-center` | Vitrine Öneriler + KVKK Uyum + Dönüşüm Hunisi modül kartları eklendi |
| 82 | **Pazarlama Sağlık Endeksi** | `/health-index` | Tüm pazarlamanın tek 0-100 stratejik puanı (6 boyut) |

Önceki personalar (Dalga 55–70): Performans paneli, Yönetici görünümü, Sektör
Kıyaslama, Hesap Sağlık Taraması (Denetim), Komuta Merkezi, Kurulum Sihirbazı,
İçerik Planlayıcı, Kreatif Lensi, Sosyal Gelen Kutusu, Aylık Bütçe Planlayıcı.

## 7. Kimlik bekleyen (no-cred) kısımlar

Aşağıdakiler canlı hesap/kimlik gerektirir ve net "kimlik bekliyor" durumundadır;
operatör kimlik bilgisi girince aktifleşir:

- **Canlı OAuth bağlama** (Google Ads/GA4/Search Console/Meta/TikTok) — broker hazır;
  client id/secret operatör tarafından girilince çalışır.
- **Sosyal medya tek-tıkla paylaşım** — yayınlama OAuth'u gerektirir (şu an 501 gate).
- **Faturalama** (Iyzico/Stripe) — anahtarlar girilince.
- **Celery zamanlı görevler** — `REDIS_URL` girilince.

## 8. Revizyon akışı

Arayüze bakıp not aldıkça, her revizyon küçük odaklı bir dalga olarak işlenebilir
(tasarla → uzman ajan → test → ekran görüntüsü → commit). Mevcut kalite çıtası:
backend **2662 test yeşil**, frontend **447 test yeşil**, tsc temiz, build yeşil.
