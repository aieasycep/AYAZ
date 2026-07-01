# 08 — Güvenlik Denetimi & Sıkılaştırma Raporu (Backend)

- **Kapsam:** `/home/user/AYAZ/backend` — auth/JWT, vault/secrets, multi-tenant izolasyon, public (auth'suz) uçlar, PII/tracking, input validation/injection, webhook'lar, rate limiting, bağımlılıklar.
- **Tarih:** 2026-06-26
- **Denetleyen:** Security & Compliance
- **Yöntem:** Gerçek kod okundu (file:line ile kanıt), saldırı senaryoları yerel olarak doğrulandı (JWT `alg=none`, feed `eval` kaçışı, production config guard). Test paketi denetim öncesi ve sonrası yeşil: **804 passed**.

---

## 1. Yönetici Özeti (Türkçe)

AYAZ backend'i, çoğu güvenlik kontrolünü **tasarımdan** doğru yapmış durumda: her tenant-scoped sorgu `tenant_id` ile filtreleniyor, JWT algoritması sabitlenmiş (`alg=none` reddediliyor), şifreler bcrypt ile saklanıyor, OAuth token'ları Fernet ile şifreli saklanıyor ve API yanıtlarında / loglarda token sızıntısı görülmedi, public uçlar 32-byte tahmin edilemez token kullanıyor, ve `EventDestinationResponse` `_secrets` alanını yanıttan temizliyor.

En kritik açık riskler **çalıştırma/yapılandırma katmanında** ve **gelecekteki canlıya geçişte**:
1. `JWT_SECRET` ve `VAULT_KEY` için **commit'lenmiş zayıf varsayılanlar** — bunlar üretime sızarsa tüm hesaplar taklit edilebilir ve tüm müşteri token'ları (crown jewels) çözülebilir. → **Düzeltildi:** üretimde güvensiz varsayılanlarla başlatmayı reddeden startup guard eklendi.
2. **Billing webhook imza doğrulaması yok** ve `tenant_id` istek gövdesinden alınıyor → abonelik/plan spoofing. → **Öneri (canlıya geçişten önce zorunlu).**
3. Public **collect / feed** uçlarında uygulama seviyesinde **rate limiting yok** → abuse/DoS. → **Öneri (altyapı + uygulama).**

Bu denetimde uygulanan düzeltmeler düşük riskli ve davranış-koruyucudur; büyük refactor'lar öneri olarak bırakılmıştır.

### Bulgu Sayıları (Severity)

| Severity | Adet | Düzeltildi | Öneri (sonraki) |
|----------|------|-----------|-----------------|
| Kritik   | 2    | 1         | 1               |
| Yüksek   | 5    | 2         | 3               |
| Orta     | 6    | 2         | 4               |
| Düşük    | 5    | 1         | 4               |
| **Toplam** | **18** | **6**   | **12**          |

---

## 2. Düzeltildi (bu denetimde uygulandı, testler yeşil)

### F-01 [Kritik] Üretimde güvensiz secret varsayılanları ile başlatma
- **Dosya:** `backend/ayaz/config.py:31` (eski `jwt_secret="changeme"`), `:50` (commit'li `vault_key`), `:46` (`vault_token="root"`).
- **Risk:** Varsayılan `jwt_secret` ("changeme") ile imzalanan JWT'ler herkesçe taklit edilebilir → tam hesap devralma + cross-tenant erişim (`tid` claim'i serbestçe ayarlanabilir). Commit'li `vault_key` ile **diskte şifreli tutulan tüm OAuth token / API key'leri** çözülebilir. Bunlar "crown jewels". Bu değerler `.env.example` dışında repo'da gömülü.
- **Düzeltme:** `Settings`'e `@model_validator(mode="after") _reject_insecure_production` eklendi. `environment == "production"` iken: güvensiz/zayıf `JWT_SECRET` (varsayılan ya da <32 karakter), commit'li `VAULT_KEY`, `VAULT_TOKEN == "root"` veya `DEBUG=True` varsa uygulama **başlamayı reddeder** (fail-fast). Dev/test varsayılanları etkilenmez (804 test yeşil). Güvensiz default sabitleri `_INSECURE_*` olarak tek yerde toplandı.
- **Kalan iş:** Üretim deploy'larında secret'ların gizli yöneticiden (Vault/SealedSecrets/SSM) gelmesi; ayrıca JWT için RS256+JWKS'e geçiş (F-09).

### F-02 [Yüksek] OAuth callback yanıtı iç hata detayını sızdırıyor
- **Dosya:** `backend/ayaz/api/v1/oauth.py` — eski `detail=f"Token exchange failed: {exc}"` ve `detail=f"Failed to store tokens: {exc}"`.
- **Risk:** Bu uç **auth'suz** (platform çağırıyor). Sağlayıcı hata gövdeleri authorization code / `client_secret` / token parçalarını yansıtabilir; ayrıca stack/DB hata mesajları sızabilir. Callback URL'i + `state` saldırgan tarafından tetiklenebildiği için bilgi sızıntısı geri okunabilir.
- **Düzeltme:** İstisnalar `logger.exception(...)` ile sunucu tarafında loglanıyor; istemciye yalnızca jenerik mesaj (`"Token exchange failed."`, `"Failed to store tokens."`) dönüyor. `logging` import edildi, modül logger'ı eklendi.

### F-03 [Yüksek] Feed `calculated` kuralında `eval()` (RCE/DoS yüzeyi)
- **Dosya:** `backend/ayaz/services/feeds.py:236-278` (`_apply_calculated`), public path: `feeds/public/{token}` → `generate_channel_feed` → `apply_rules`.
- **Analiz (doğrulandı):** Mevcut karakter-sınıfı guard'ı (`re.fullmatch(r"[\d\s\+\-\*/\.\(\)]+", ...)`) `__import__(...)` gibi kod enjeksiyonunu **engelliyor** (kanıt: non-numeric ifade `eval`'e ulaşmadan `format_map`'e düşüyor). Tüm operandlar `float`'a çevrildiği için `**` ile devasa tamsayı üretip CPU/RAM DoS yapma da pratikte `inf`'e taşıyor. Yani **şu an exploit edilemiyor**; ancak `eval` + tenant-kontrollü girdi + auth'suz tetikleyici kombinasyonu kabul edilemez bir kalıp.
- **Düzeltme (defense-in-depth):** Eval yolunda `**` (üs) açıkça reddedildi (asla meşru fiyat matematiği için gerekmez; tek tehlikeli aritmetik yapı). `**` içeren ifade `eval` yerine güvenli `format_map`'e düşüyor. Legitimate `{price} * 0.9` ve `{title} - {brand}` davranışı korunuyor (testler yeşil).
- **Kalan iş (Öneri R-03):** `eval` tamamen kaldırılıp güvenli bir aritmetik değerlendirici (örn. `ast.parse` + whitelisted node walk, ya da küçük bir shunting-yard) ile değiştirilmeli.

### F-04 [Orta] JWT `exp` claim'i zorunlu değildi
- **Dosya:** `backend/ayaz/services/auth.py:75-87` (`decode_access_token`).
- **Risk:** `exp` claim'i olmayan bir token süresiz kabul edilebilirdi (algoritma zaten sabit olduğu için forge imkânsız, ama `exp`'siz meşru/eski token kalıpları riskli).
- **Düzeltme:** `options={"require_exp": True}` eklendi; `exp` içermeyen token reddediliyor (python-jose 3.5.0'da doğrulandı). Algoritma sabitleme (`algorithms=[...]`) ve `alg=none` reddi zaten mevcuttu; kod yorumu ile netleştirildi.

### F-05 [Orta] Feed `calculated` DoS yüzeyi (üs operatörü)
- Bkz. F-03 düzeltmesinin DoS bileşeni. `**` engellendi.

### F-06 [Düşük] Güvensiz default'lar tek kaynağa toplanmadı / DEBUG üretimde açık olabiliyordu
- **Dosya:** `backend/ayaz/config.py`.
- **Düzeltme:** `_INSECURE_*` sabitleri + production guard içinde `DEBUG=True` reddi (F-01 ile birlikte). Üretimde `DEBUG` açıkken `/docs` ve `/redoc` da açılıyordu (`main.py:38-39`) — guard bunu da kapatıyor.

---

## 3. Öneri (sonraki — uygulanmadı, davranış değişikliği/efor gerektiriyor)

### R-01 [Kritik] Billing webhook: imza doğrulaması yok + `tenant_id` gövdeden geliyor (SPOOFING)
- **Dosya:** `backend/ayaz/api/v1/billing.py:257-303`, `backend/ayaz/services/billing.py:455-475, 517-536, 579-598, 601-633`.
- **Risk:** `POST /billing/webhook/{provider}` auth'suz. `tenant_id` **istek gövdesinden** okunuyor ve `plan_code`/`status` doğrudan uygulanıyor (`_apply_webhook_plan_change`). İmza doğrulanmadığı için herhangi biri istediği tenant'ı istediği plana (örn. `agency`) yükseltebilir / iptal edebilir → ücret kaçağı + yetkisiz entitlement. Kod içinde `TODO (Faz 1): verify HMAC/signature` notu mevcut.
- **Öneri (canlıya geçişten önce ZORUNLU):**
  1. Stripe: `Stripe-Signature` header'ını `stripe_webhook_secret` ile doğrula (ham body üzerinde HMAC-SHA256, timestamp tolerans kontrolü).
  2. iyzico: sağlayıcının HMAC şemasını doğrula.
  3. `tenant_id`'yi **asla** gövdeden alma; sağlayıcı `customer_id`/`subscription_id` → `Subscription` eşlemesiyle çöz.
  4. İmza secret'ı yapılandırılmış (live) modda imzasız/geçersiz istekleri `400/401` ile reddet (replay koruması için event idempotency anahtarı sakla).

### R-02 [Yüksek] Public uçlarda rate limiting / abuse koruması yok
- **Dosya:** `tracking/collect/{token}` (`api/v1/tracking.py:534-579`), `feeds/public/{token}` (`api/v1/feeds.py:680-705`), `reports/public/{token}` (`api/v1/reports.py:624-698`), `auth/login` (`api/v1/auth.py:131`), `auth/signup`.
- **Risk:** `collect` her POST'ta DB insert + harici platform forward tetikliyor → kaynak tükenmesi ve maliyet artışı (her event çoklu CAPI çağrısı). `login` brute-force'a açık (lockout yok). `reports/public` her görüntülemede tam rapor üretiyor (ağır SQL). Kod yorumu rate limiting'i "altyapı/WAF" katmanına bırakıyor ama uygulama içi minimum koruma yok.
- **Öneri:**
  1. Reverse-proxy/WAF seviyesinde IP+token bazlı rate limit (collect için yüksek, login için düşük).
  2. Uygulama içi `slowapi`/Redis tabanlı limiter (özellikle `login`: IP+email başına deneme sayacı + üstel gecikme/lockout).
  3. `collect` payload boyutu/anahtar sayısı sınırı (aşağıda R-06).

### R-03 [Yüksek] `eval` tamamen kaldırılmalı (feed rule engine)
- Bkz. F-03. `**` engellendi ama `eval` kalıbı uzun vadede `ast`-tabanlı güvenli değerlendiriciyle değiştirilmeli. Birim testlerle (template + arithmetic + kötü girdi) kapsanmalı.

### R-04 [Yüksek] JWT iptal/refresh mekanizması yok; tenant değiştirince eski token geçerli kalıyor
- **Dosya:** `services/auth.py:11-12` (refresh yok), `services/workspaces.py:22-24` (switch sonrası eski token expiry'e kadar geçerli).
- **Risk:** Token sızarsa expiry'e (60 dk) kadar iptal edilemez. Üye çıkarıldığında / rol düşürüldüğünde / workspace değişiminde eski JWT hâlâ geçerli. `get_current_membership` her istekte membership'i DB'den doğruluyor (iyi), ama JWT'nin kendisi iptal edilemiyor.
- **Öneri:** Kısa ömürlü access token + refresh token rotation; Redis tabanlı revocation/`jti` deny-list; üyelik silindiğinde ilgili tenant token'larını geçersiz kılma.

### R-05 [Orta] OAuth `state` token'ı imzalı/MAC'li değil (CSRF/bütünlük)
- **Dosya:** `services/oauth_broker.py:120-156` (`_sign_state`/`parse_state`).
- **Risk:** `state` sadece base64(JSON) — imzalı değil. `aid`/`tid` istemci tarafından üretilebilir. Callback `account`'u `(id, tenant_id)` ile DB'den doğruluyor (cross-tenant binding'i koruyor), ama gerçek CSRF koruması (kullanıcı oturumuna bağlı, kısa ömürlü, tek kullanımlık state) yok. Kod yorumu bunu kabul ediyor.
- **Öneri:** `state`'i HMAC (kısa ömürlü per-session secret) ile imzala + nonce/expiry + tek kullanım. Callback'te imzayı doğrula.

### R-06 [Orta] Public collect/feed girdi boyutu sınırsız
- **Dosya:** `api/v1/tracking.py:540` (`payload: dict[str, Any]` sınırsız), `api/v1/feeds.py:419` (`file.file.read()` tüm dosyayı belleğe alıyor), `services/feeds.py:148` (`source_url` fetch — bkz R-07).
- **Risk:** Büyük JSON / büyük upload → bellek/CPU DoS. `collect` derinliği/anahtar sayısı doğrulanmıyor.
- **Öneri:** Body boyutu limiti (proxy + app), `collect` için Pydantic modeli ile alan whitelist'i ve maksimum boyut, upload için streaming + boyut tavanı.

### R-07 [Orta] Feed source URL fetch — SSRF riski
- **Dosya:** `services/feeds.py:143-155` (`httpx.get(source_url, follow_redirects=True)`).
- **Risk:** Tenant `source_url` belirliyor; sunucu bu URL'i çekiyor. `follow_redirects=True` ile internal/metadata endpoint'lerine (örn. `169.254.169.254`, `localhost`, internal servisler) SSRF mümkün.
- **Öneri:** URL şeması whitelist'i (`http/https`), DNS çözümleme sonrası private/loopback/link-local IP bloğu reddi, redirect'lerde yeniden doğrulama, dış egress için ayrı kısıtlı network/proxy, timeout + boyut limiti.

### R-08 [Orta] RLS (Row-Level Security) henüz aktif değil — izolasyon tek katmana bağlı
- **Dosya:** `api/deps.py:90-100` (TODO RLS), çoklu servis WHERE filtreleri.
- **Risk:** Tüm tenant izolasyonu **uygulama katmanındaki explicit `WHERE tenant_id`** filtrelerine bağlı. Bu denetimde tüm tenant-scoped sorgular doğru filtreli bulundu (aşağıdaki tabloya bakınız), ancak tek bir unutulan filtre cross-tenant sızıntı demek. Defense-in-depth eksik.
- **Öneri:** Postgres RLS politikalarını etkinleştir; her istekte `set_config('app.tenant_id', ...)` ile session'a tenant bağla. Uygulama filtreleri korunsun (iki katman).

### R-09 [Düşük] CORS `allow_credentials=True` + `allow_headers/methods="*"`
- **Dosya:** `main.py:43-49`.
- **Risk:** `allow_origins` yapılandırılabilir (iyi) ama `*` origin ile birlikte credentials kullanımı yanlış yapılandırılırsa tehlikeli. Şu an liste tabanlı; yine de üretimde origin listesinin sıkı tutulması ve `*`'a düşülmemesi gerekir.
- **Öneri:** Üretimde origin'leri açık liste tut; `allow_headers`/`allow_methods` gerçekten gerekenlerle sınırla.

### R-10 [Düşük] Şifre politikası minimal (yalnızca uzunluk ≥ 8), MFA yok
- **Dosya:** `api/v1/auth.py:35-40`.
- **Risk:** Karmaşıklık/breached-password kontrolü yok; MFA yok; brute-force koruması yok (R-02).
- **Öneri:** Min 12 karakter + zayıf/sızmış parola reddi (HaveIBeenPwned k-anon), TOTP MFA (özellikle owner/admin), login lockout.

### R-11 [Düşük] Davet/paylaşım token'ları API yanıtında dönüyor
- **Dosya:** `api/v1/workspaces.py:159` (`InvitationResponse.token`), `services/workspaces.py:343` ve `reports.py` paylaşım yanıtı `public_token` döndürüyor (tasarım gereği), `tracking.py`/`feeds.py` `public_token` döndürüyor.
- **Risk:** `InvitationResponse.token` üretimde UI'a dönmemeli (yorumda "hide in prod UI" notu var); e-posta ile gitmeli. Public token'lar tasarım gereği sahibe gösteriliyor (kabul edilebilir) ama log/erişim kayıtları sıkı olmalı.
- **Öneri:** Üretim modunda davet token'ını yanıttan çıkar; yalnızca e-posta ile ilet.

### R-12 [Düşük] Token rotasyonu / iptal süreçleri (OAuth + tracking/feed public token)
- **Dosya:** `connectors/accounts` delete (`api/v1/connectors.py:170` "TODO: revoke OAuth token"), public token rotasyonu manuel.
- **Öneri:** Hesap silinince Vault token'ını sağlayıcıda revoke et + Vault'tan sil. Public token'lar için kolay rotasyon endpoint'i.

---

## 4. Doğrulanan Güçlü Yönler (kanıtla)

- **JWT algoritma sabitleme:** `services/auth.py:83-87` `algorithms=[settings.jwt_algorithm]`. `alg=none` forge denemesi `JWTError` ile reddedildi (yerel doğrulama).
- **Şifre hashleme:** bcrypt via passlib, `services/auth.py:24,30-37`.
- **Vault şifreleme:** Fernet (AES-128-CBC + HMAC), PBKDF2-HMAC-SHA256 (100k iter) key derivation, `services/vault.py:54-79,165-181`. `InvalidToken` → `None` (crash yok).
- **Token sızıntısı yok:** OAuth/secret değerleri loglanmıyor. Connector logları yalnızca "Authenticated…/refreshed" diyor, token değeri yok (`connectors/*.py`). `_secrets` DB'ye yazılmıyor (`services/tracking.py:403-431`) ve `EventDestinationResponse` `_secrets`'i yanıttan temizliyor (`api/v1/tracking.py:190-193`).
- **PII politikası:** Raw email/phone hash'lenip atılıyor; raw veri persist/log edilmiyor (`services/tracking.py:120-176`). Consent zorlaması mevcut (`:309-318`), `consent_required` destinasyon bazlı.
- **Report HTML XSS:** Tüm kullanıcı-kontrollü değerler `_esc` (`html.escape`) ile kaçırılıyor — brand_name, logo_url, primary_color, channel, insight title/body, dates (`services/reports.py:376-378,453-598`). CSV/XML render `csv`/`ElementTree` ile yapılıyor (string concat değil).
- **SQL injection:** Tüm sorgular SQLAlchemy ORM/`select()` ile parametreli; ham SQL string interpolation bulunamadı.
- **Public token kalitesi:** `secrets.token_urlsafe(32)` (feeds/reports/tracking/invitations) — tahmin edilemez.

### Multi-tenant izolasyon denetimi (tenant-scoped sorgular)

| Modül | Filtre durumu |
|-------|---------------|
| dashboard (`summary`, `timeseries`) | ✅ `FactDailyMetrics.tenant_id == tenant_id` |
| ads (`list/detail/recommendations`) | ✅ servis `tenant_id` parametresi |
| insights (+ alert-rules) | ✅ her sorgu `tenant_id` |
| reports (definition/schedule/share/preview) | ✅ `_require_*` + payload `tenant_id` |
| feeds (source/channel/rule/products) | ✅ `_require_*` + `generate_channel_feed` `tenant_id` |
| automation (rule/run) | ✅ `_get_rule_or_404` + runs `tenant_id` |
| tracking (source/dest/events) | ✅ `_require_*`; events parent source ile bağlı |
| billing | ✅ `membership.tenant_id` (webhook hariç — R-01) |
| workspaces (members/invites) | ✅ her sorgu `tenant_id` (last-owner guard'ları var) |
| connectors (accounts) | ✅ `tenant_id` filtreli |
| oauth callback | ✅ `state` decode → `(id, tenant_id)` ile DB doğrulaması |

> Not: Bu denetimde **tenant filtresi eksik bir sorgu bulunamadı**; bu nedenle "eksik filtre ekleme" düzeltmesi uygulanmadı. İzolasyon tek katman (uygulama) — defense-in-depth için RLS önerilir (R-08).

---

## 5. OWASP Top 10 (2021) Hızlı Eşleme

| Kategori | Durum / Bulgu |
|----------|---------------|
| A01 Broken Access Control | İyi (tenant filtreleri); RLS yok (R-08), webhook spoofing (R-01) |
| A02 Cryptographic Failures | Vault/JWT sağlam; güvensiz default'lar (F-01 düzeltildi) |
| A03 Injection | SQL yok; XSS escape'li; `eval` yüzeyi (F-03 sıkılaştırıldı, R-03) |
| A04 Insecure Design | Webhook tenant-from-body (R-01); rate limit yok (R-02) |
| A05 Security Misconfiguration | Prod default guard (F-01), DEBUG/docs (F-06), CORS (R-09) |
| A06 Vulnerable Components | Bkz. §6 — pinler makul, otomatik tarama önerilir |
| A07 Auth Failures | MFA/lockout yok (R-10), token revocation yok (R-04) |
| A08 Data Integrity | Webhook imzası yok (R-01) |
| A09 Logging/Monitoring | Token loglanmıyor (iyi); merkezi audit/alerting önerilir |
| A10 SSRF | Feed URL fetch (R-07) |

---

## 6. Bağımlılıklar

- `python-jose[cryptography]>=3.3.0`, `passlib[bcrypt]`, `bcrypt>=4,<5`, `cryptography>=42,<44`, `fastapi>=0.111`, `sqlalchemy>=2.0.30`, `pydantic>=2.7`.
- Gözlem: pinler güncel ve makul; bilinen riskli kalıp (örn. eski `python-jose` JWT bypass'leri 3.3+ ile kapalı). `eval` haricinde tehlikeli runtime kullanımı yok.
- **Öneri:** CI'da `pip-audit`/Dependabot ile sürekli SCA; `python-jose` yerine bakımı daha aktif `pyjwt`'ye geçiş değerlendirilebilir.

---

## 7. KVKK (Türkiye) / GDPR (AB) Uyumluluk Kontrol Listesi

> Hukuki tamlık değil, mühendislik kontrol listesidir.

### Yapıldı / kodda mevcut
- [x] **PII minimizasyonu & hashing:** Raw email/phone hash'lenip atılıyor, persist/log yok (`services/tracking.py`).
- [x] **Consent zorlaması (tracking):** `consent` yoksa ve destinasyon `consent_required` ise event forward edilmiyor (`skipped_no_consent`).
- [x] **Şifrelenmiş secret saklama:** OAuth token/API key Fernet ile at-rest şifreli.
- [x] **Tenant veri izolasyonu:** Uygulama katmanında tutarlı `tenant_id` filtreleri.
- [x] **Audit izleri (kısmi):** `BillingEvent`, `AutomationRun`, davet `invited_by`.

### Eksik / yapılacak (Öneri)
- [ ] **Veri ikametgâhı (data residency):** KVKK için TR / GDPR için AB bölgesinde barındırma ve sub-processor lokasyon dökümü netleştirilmeli.
- [ ] **Silme hakkı (right to erasure):** Tenant/kullanıcı ve PII (ConversionEvent) için kalıcı silme/anonimleştirme akışı yok.
- [ ] **Taşınabilirlik/erişim hakkı (export):** Kullanıcı verisini dışa aktarma endpoint'i yok.
- [ ] **Saklama süreleri (retention):** ConversionEvent / metrik / log için TTL ve otomatik temizleme politikası yok.
- [ ] **Consent kayıt kanıtı:** Sadece boolean `consent` saklanıyor; consent zamanı/versiyonu/kaynağı (audit) saklanmalı.
- [ ] **DPA & sub-processor envanteri:** Meta/Google/TikTok/iyzico/Stripe vb. için DPA ve veri-akış haritası dokümante edilmeli.
- [ ] **İhlal bildirimi süreci:** 72 saat içinde bildirim (GDPR) operasyonel runbook'u.
- [ ] **MFA & güçlü auth (R-10):** Yönetici hesapları için zorunlu MFA.
- [ ] **Webhook bütünlüğü (R-01):** Ödeme/abonelik verisi spoofing'e karşı korunmalı.
- [ ] **Log içinde PII olmaması:** Mevcut durumda iyi; merkezi logda PII/secret yasağı politika olarak sabitlenmeli.

---

## 8. Uygulanan Değişiklikler — Dosya Özeti

| Dosya | Değişiklik |
|-------|------------|
| `backend/ayaz/config.py` | `_INSECURE_*` sabitleri; `_reject_insecure_production` model validator (prod'da zayıf JWT_SECRET/VAULT_KEY/VAULT_TOKEN/DEBUG → başlatmayı reddet). |
| `backend/ayaz/services/auth.py` | `decode_access_token` → `options={"require_exp": True}`; algoritma sabitleme açıklaması. |
| `backend/ayaz/api/v1/oauth.py` | Callback hata yanıtlarından iç detay kaldırıldı; `logger.exception` ile sunucu-tarafı loglama. |
| `backend/ayaz/services/feeds.py` | `_apply_calculated` eval yolunda `**` (üs) reddi (DoS defense-in-depth). |

**Test durumu:** `cd backend && pytest -q` → **804 passed** (denetim öncesi ve sonrası aynı).

---

## 9. Önceliklendirilmiş Yapılacaklar (özet)

1. **R-01 (Kritik):** Webhook imza doğrulama + `tenant_id`'yi gövdeden alma — *canlı ödeme öncesi zorunlu*.
2. **R-02 (Yüksek):** Rate limiting (login brute-force + public collect/feed abuse).
3. **R-04 (Yüksek):** JWT refresh/revocation (Redis deny-list).
4. **R-03 (Yüksek):** Feed `eval` → AST tabanlı güvenli evaluator.
5. **R-07 (Orta):** Feed URL fetch SSRF koruması.
6. **R-08 (Orta):** Postgres RLS (izolasyon ikinci katmanı).
7. **KVKK/GDPR:** silme/export/retention/consent-kanıtı akışları.
