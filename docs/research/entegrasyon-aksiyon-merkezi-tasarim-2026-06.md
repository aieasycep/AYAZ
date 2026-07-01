# AYAZ — Entegrasyon & Aksiyon Merkezi (Native Composio Alternatifi)

> **Tasarım dokümanı — mühendislik ekibine teslim edilebilir.** Tarih: 2026-06-30
> Yazar: Solution Architect. Durum: tasarım (uygulama kodu DEĞİŞTİRİLMEDİ).
>
> **Kapsam:** Müşterinin TÜM entegrasyonları kendi başına, mümkün olan en hızlı ve
> en az tıklamayla bağlayabildiği; bağlanan her entegrasyonun hem **veri kaynağı**
> hem de **Copilot aksiyonu** olarak otomatik kayıt olduğu; tüm token'ların AYAZ'ın
> kendi Vault'unda (3. taraf broker yok, sınır ötesi transfer yok) tutulduğu bir
> "tek çatı" entegrasyon platformu.

---

## 0. KUZEY YILDIZI (her kararı yöneten tek gereksinim)

> **Müşteri, geliştirici/operatör müdahalesi olmadan, neredeyse sıfır sürtünmeyle,
> mümkün olduğunca çok entegrasyonu dakikalar içinde kendisi açabilmeli.**
> "Bağla'ya tıkla → OAuth açılır penceresi → bitti."

Bu doküman boyunca her tasarım kararı şu metriğe göre optimize edilir:
**bağlanma süresi (time-to-connected) ve tıklama sayısı minimum, dakikada açılan
entegrasyon sayısı maksimum.** Hedef kitle teknik olmayan TR pazarlamacı/ajans.

Bunu mümkün kılan **mimari kaldıraç** zaten kısmen kodda mevcuttur ve bu tasarımın
temelidir: **platforma-ait (platform-owned) OAuth uygulamaları.** Müşteri asla
`client_id`/`client_secret` girmez; AYAZ her sağlayıcıda kendi OAuth app'ini bir
kez kaydeder, müşteri sadece "Bağla → izin ver" yapar.

---

## 1. YÖNETİCİ ÖZETİ

AYAZ'ın bağlayıcı (connector) katmanı, OAuth broker'ı ve Vault'u **olgun ve doğru
mimarlanmış** durumda. Composio'nun yaptığı işin %70'i kemik düzeyinde zaten var:

- `Connector` ABC + `ConnectorRegistry` otomatik kayıt (`__init_subclass__`) —
  `backend/ayaz/connectors/base.py`, `registry.py`
- 10 bağlayıcı (`google_ads`, `meta_ads`, `ga4`, `search_console`, `tiktok_ads`,
  `linkedin_ads`, `microsoft_ads`, `criteo`, `pinterest_ads`, `sample`)
- **Platforma-ait** OAuth broker — `settings`'ten `client_id/secret`, müşteri
  değil — `backend/ayaz/services/oauth_broker.py`
- Per-tenant Fernet-şifreli Vault — `backend/ayaz/services/vault.py`
- Claude tool-calling katmanı (`TOOL_SPECS` + `dispatch` + `ACTION_TOOLS`) —
  `backend/ayaz/services/copilot_tools.py`, `copilot.py`
- Multi-tenancy (`Tenant`/`Membership`/`tenant_id`) — `backend/ayaz/models/oltp.py`
- Plan-gating (`require_within_data_source_limit`) — `backend/ayaz/services/billing.py`

**Eksik olan** (bu dokümanın inşa ettiği) tek-katmanlı bir parça: bunların hepsini
**tek bir müşteri-yüzeyi (Entegrasyon Merkezi)** + **tek bir adaptör soyutlaması**
(veri OKUMA + aksiyon YAZMA birlikte) + **otomatik Copilot araç kaydı** altında
birleştiren orkestrasyon. Yani: motor var, kaporta + tek pedal yok.

### En kritik 8 karar (ADR özeti)

| # | Karar | Gerekçe | Reddedilen alternatif |
|---|---|---|---|
| ADR-1 | **Build (native), Composio'yu entegre etme** | KVKK/veri ikametgâhı kontrolü, öngörülebilir maliyet, "tek çatı" moat | Composio SaaS (token'lar 3. tarafta → KVKK riski) |
| ADR-2 | **Platforma-ait OAuth app'ler** (zaten broker'da var) | Müşteri sıfır kimlik girer; tek tık bağlanır | Müşterinin kendi app'ini kaydetmesi (BYO — sürtünme felaketi) |
| ADR-3 | **Tek `Integration` adaptör arayüzü; OKUMA + YAZMA birlikte** | Yeni entegrasyon < 1 gün; tek kayıt noktası | OKUMA `Connector` ve YAZMA için ayrı sistem (çift bakım) |
| ADR-4 | **Tek sağlayıcı OAuth → çok ürün** (Google → Ads+GA4+SC bundled scope) | Tek consent ile 3 entegrasyon açılır → time-to-connected çöker | Her ürün ayrı OAuth (3 popup, 3 consent) |
| ADR-5 | **Bağlanan her entegrasyon Copilot aracı olarak otomatik kayıt** | Veri ↔ aksiyon birleşik kokpit; manuel TOOL_SPECS yazımı bitter | Elle her araç için spec yazmak (mevcut durum) |
| ADR-6 | **Yeni `integration_connections` tablosu; `ConnectedAccount` reklam/analitik için kalır** | Mevcut sync motoru bozulmaz; "aksiyon" entegrasyonları farklı yaşam döngüsü | Her şeyi `ConnectedAccount`'a tıkıştırmak (anlamsal bulanıklık) |
| ADR-7 | **Curated ~25 entegrasyon, talep-güdümlü; 500+ peşinde KOŞMA** | TR-ICP odağı, bakım yükü kontrolü, kalite | Composio'nun genişliğini taklit (sürdürülemez) |
| ADR-8 | **Tüm yazma aksiyonlarında onay-öncesi + audit log + per-action yetki** | KVKK + güven + geri alınamaz aksiyon koruması | Otomatik yürütme (kullanıcı kontrolü kaybı) |

---

## 2. MEVCUT DURUM vs EKSİK (dosya referanslı)

| Yetenek | Durum | Dosya(lar) | Eksik / Yapılacak |
|---|---|---|---|
| Connector ABC + capabilities | **VAR** | `backend/ayaz/connectors/base.py` | Sadece OKUMA tanımlı (`fetch/normalize`); `supports_write` flag var ama yazma metodu yok |
| Connector auto-registry | **VAR** | `backend/ayaz/connectors/registry.py` | Aksiyon/araç kaydı eklenecek (paralel registry veya genişletme) |
| 10 bağlayıcı | **VAR** | `connectors/{google_ads,meta_ads,ga4,search_console,tiktok_ads,linkedin_ads,microsoft_ads,criteo,pinterest_ads,sample}.py` | Hepsi reklam/analitik OKUMA. Aksiyon entegrasyonu (Slack/Sheets/Gmail/WhatsApp/sosyal yayın) **YOK** |
| OAuth broker (platforma-ait) | **VAR** | `backend/ayaz/services/oauth_broker.py` | Sadece 3 sağlayıcı config'i (Google/Meta/TikTok). PKCE yok; `state` HMAC-imzalı değil; refresh lifecycle job'ı yok |
| OAuth API (authorize/callback) | **VAR** | `backend/ayaz/api/v1/oauth.py` | `_DEFAULT_REDIRECT_BASE = http://localhost:8000` hard-coded; callback JSON döner, SPA success URL'ine redirect etmez; popup yerine `window.location` |
| Vault (Fernet, per-tenant) | **VAR** | `backend/ayaz/services/vault.py` | `EncryptedColumnVault` token'ı `connected_accounts.vault_secret_ref`'e yazar. Aksiyon entegrasyonları için ayrı saklama gerek (yeni tablo) |
| Token refresh fonksiyonu | **VAR** | `oauth_broker.refresh()` | Çağıran yok — proaktif yenileme job'ı (`tasks/`) **YOK**; `Connector.refresh_token()` abstract ama Vault'a yazmıyor (TODO Faz 1) |
| ConnectedAccount modeli | **VAR** | `backend/ayaz/models/oltp.py` | `scopes`, `last_health_check`, `connected_by_user_id`, `provider_user_email` kolonları **YOK** |
| Platform / SyncStatus enum | **VAR** | `oltp.py` | `Platform` 8 + `sample`; aksiyon platformları (slack, google_sheets…) **YOK**. `SyncStatus` {idle,syncing,success,error,paused} |
| Copilot tool registry | **VAR** | `backend/ayaz/services/copilot_tools.py` | `TOOL_SPECS` elle yazılı, statik. Bağlantı-farkında değil; her tenant aynı araçları görür. Aksiyon araçları sadece `create_automation_rule/create_goal` |
| Copilot Claude loop | **VAR** | `backend/ayaz/services/copilot.py` | `TOOL_SPECS` doğrudan import; per-tenant filtreleme **YOK**; yazma onayı sadece prompt-seviyesinde |
| Connectors API CRUD | **VAR (iskelet)** | `backend/ayaz/api/v1/connectors.py` | Katalog endpoint'i yok (`GET /integrations`); disconnect token revoke etmiyor (TODO); role-check yok (TODO) |
| Billing data-source gate | **VAR** | `backend/ayaz/services/billing.py` | Aksiyon entegrasyonları için ayrı sayım/gate yok |
| Frontend `/connections` | **VAR** | `frontend/src/app/connections/page.tsx` | Statik 9 platform listesi (kod içinde gömülü); katalog/arama/kategori/filtre **YOK**; redirect (popup değil); sadece reklam platformları |
| Frontend `/onboarding` | **VAR** | `frontend/src/app/onboarding/page.tsx` | Checklist var ama "Bağlantı Sihirbazı" / akıllı öneri / tek-akışta-bağla yok |
| Sidebar "Veri & Entegrasyon" | **VAR** | `frontend/src/components/AppNav.tsx` (NAV_GROUPS) | `/connections, /feeds, /tracking, /consent`. "Entegrasyon Merkezi" linki eklenecek |
| connectors-api.ts | **VAR** | `frontend/src/lib/connectors-api.ts` | SyncStatus map'i backend ile uyumsuzluğu maskeliyor (`idle→pending`, `success→connected`); katalog tipi yok |
| Tasarım sistemi (tokenlar) | **VAR** | `frontend/src/app/globals.css`, `components/{EmptyState,SectionCard,KpiCard,...}.tsx` | Yeniden kullanılacak; yeni "IntegrationCard" bileşeni eklenecek |

**Sonuç:** Backend motoru olgun. İş kalemleri çoğunlukla **birleştirme** (orchestration)
ve **müşteri-yüzeyi** (UX) — sıfırdan inşa değil.

---

## 3. MÜŞTERİ BAĞLANMA UX (KALP — en detaylı bölüm)

> Bu, ürünün en kritik ekranı. North Star buraya gömülüdür: **en az tıklama, en kısa süre.**

### 3.1 Bilgi mimarisi & navigasyon

Sidebar "Veri & Entegrasyon" grubuna **en üste** yeni bir link:

```
Veri & Entegrasyon
  ├─ Entegrasyon Merkezi   →  /integrations      ← YENİ (ana yüzey)
  ├─ Bağlantılar           →  /connections       (mevcut — "Bağlı Hesaplarım" detayına döner)
  ├─ Feed Yönetimi         →  /feeds
  ├─ Ölçümleme             →  /tracking
  └─ KVKK Rıza Merkezi     →  /consent
```

`/integrations` = **katalog + bağlama** (keşif). `/connections` = **bağlı hesap
yönetimi** (sağlık, yeniden bağla, kaldır). İkisini ayırmak North Star'a hizmet
eder: keşif ekranı "ne bağlayabilirim?" sorusuna sürtünmesiz cevap verir.

### 3.2 Entegrasyon Merkezi ekranı (`/integrations`)

RADAAR'ın "Genel" dashboard'undaki **"Başlamadan Önce" checklist** ve kanal-kartı
mantığını AYAZ tasarım diline (globals.css token'ları, `SectionCard`) harmanlıyoruz.

**Layout (ASCII wireframe):**

```
┌────────────────────────────────────────────────────────────────────────────┐
│  Entegrasyon Merkezi                                    [+ Hepsini Bağla*]   │
│  Tüm reklam, analitik ve aksiyon araçlarınızı tek yerden bağlayın.           │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ İlerleme: 4/25 bağlı  ▓▓▓░░░░░░░  %16   "İlk verinize 1 bağlantı kaldı"│  │ ← ProgressHero
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  [🔍 Ara: "google", "slack"...        ]   Durum:[Tümü|Bağlı|Bağlanabilir]   │ ← arama + filtre
│                                                                              │
│  Tümü  Reklam  Analitik  Sosyal  Mesajlaşma  E-ticaret  Üretkenlik          │ ← kategori sekmeleri
│  ────                                                                        │
│                                                                              │
│  ÖNERİLEN (sektörünüze göre)                                                 │ ← akıllı öneri şeridi
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                                     │
│  │ G Google │ │ M Meta   │ │ # Slack  │                                     │
│  │ Ads+GA4..│ │ Ads      │ │ Bildirim │                                     │
│  │ [Bağla→] │ │ [Bağla→] │ │ [Bağla→] │                                     │
│  └──────────┘ └──────────┘ └──────────┘                                     │
│                                                                              │
│  REKLAM                                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                        │
│  │●Google Ad│ │ Meta Ads │ │TikTok Ads│ │LinkedIn  │                        │
│  │ Bağlı ✓  │ │[Bağla]   │ │[Bağla]   │ │ Yakında  │                        │
│  │2dk önce  │ │          │ │          │ │ (gri)    │                        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘                        │
│  ...                                                                         │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Kart durumları (3 state):**

- **Bağlı** (yeşil nokta `--color-success`): "Bağlı ✓", son senkron zamanı, ufak
  menü (⋮ → Yeniden bağla / Sağlık / Kaldır). Sağlık bozuksa kart kenarı amber/kırmızı.
- **Bağlanabilir** (`--color-primary` "Bağla" butonu): tek tık → 3.3 akışı.
- **Yakında** (gri, `--color-text-muted`): "Yakında" rozeti + "Haber ver" linki
  (talep sinyali toplar → katalog önceliklendirme). Buton pasif.

**Kart anatomisi** (yeni `IntegrationCard` bileşeni, `SectionCard` token'larıyla):
ikon (marka rengi arka plan, mevcut `connections/page.tsx` deseni), ad, tek-satır
açıklama, kategori rozeti, sağ-üst durum rozeti, alt CTA.

**Filtre & arama:** İstemci-tarafı filtre (katalog ~25 öğe, sayfalama gereksiz).
Arama hem ada hem takma-adlara (alias) bakar ("analitik" → GA4, "bildirim" → Slack).

### 3.3 Tek-tık bağlama akışı (the heart of the heart)

**Standart OAuth (Google/Meta/TikTok/LinkedIn/Slack/...):**

```
[Bağla]  →  POST /api/v1/integrations/{key}/connect
         →  { authorize_url, connection_id, mode: "popup" }
         →  window.open(authorize_url, 'ayaz_oauth', 'width=600,height=720')   ← POPUP
         →  (sağlayıcı consent ekranı — AYAZ logosu, white-label destekliyorsa)
         →  sağlayıcı → GET /api/v1/oauth/{provider}/callback?code&state
         →  backend: code→token exchange, Vault.put, discover(), durum=connected
         →  callback HTML: window.opener.postMessage({type:'ayaz:oauth:done', connection_id, status})
            + window.close()
         →  ana pencere mesajı alır → kartı "Bağlanıyor…" → "Bağlı ✓" yapar (sayfa yenilenmez)
         →  arka planda ilk discover + ilk sync tetiklenir
```

**Neden popup, redirect değil?** Mevcut kod `window.location.href = authorize_url`
kullanıyor (`connections/page.tsx:120`) — bu tüm uygulamadan çıkış demek; dönüşte
state kaybı, "nerede kalmıştım" hissi. **Popup + postMessage** ile müşteri
Entegrasyon Merkezi'nde kalır, kart anında güncellenir; **art arda 5 entegrasyonu
sayfadan ayrılmadan açabilir.** Bu doğrudan North Star metriği.

**Tıklama sayısı:** Bağla (1) → sağlayıcı "İzin Ver" (1) = **2 tık, ~10-20 sn.**

#### 3.3.1 Tek sağlayıcı → çok ürün (ADR-4, kritik hız kazanımı)

Google bir OAuth uygulamasıdır ama AYAZ'da 3 ürüne karşılık gelir:
**Google Ads + GA4 + Search Console.** Bunları **tek consent'te** açmak time-to-connected'i
3 kat düşürür.

**Tasarım:** Katalogda iki sunum:
- **"Google Workspace" birleşik kartı** (önerilen): "Bağla" → tek OAuth, **bundled
  scope** (adwords + analytics.readonly + webmasters.readonly). Consent sonrası
  `discover()` üç ürünün de erişimini bulur ve **3 ayrı `IntegrationConnection`**
  oluşturur (ortak `provider_grant_id`'ye bağlı). Müşteri "izin ver"e bir kez basar,
  3 entegrasyon yeşile döner.
- Alternatif: ayrı kartlar (yalnızca GA4 isteyen için), ama varsayılan birleşik.

**Backend:** `oauth_broker._PLATFORM_CONFIGS`'e `google_workspace` provider'ı:
`scopes=[adwords, analytics.readonly, webmasters.readonly]`. Callback, dönen token'ı
**tek Vault kaydına** (`provider_grant`) yazar; üç `IntegrationConnection` aynı
grant'i `vault_secret_ref` ile paylaşır. Token tek; ürünler grant'i paylaşır.

> **Genişletilebilir desen:** Meta (Ads + Instagram + Facebook Page + WhatsApp Business)
> ve Google aynı "tek grant → çok ürün" modelini kullanır. Bu, kataloğun
> "dakikada çok entegrasyon" hedefini taşıyan ana mekanizma.

```
Google Workspace OAuth (tek consent, 3 scope)
        │ token (tek grant)
        ▼
  provider_grant (Vault: enc:...)   provider_grant_id = G1
   ├─ IntegrationConnection(google_ads,        grant=G1, capabilities=[read])
   ├─ IntegrationConnection(ga4,               grant=G1, capabilities=[read])
   └─ IntegrationConnection(search_console,    grant=G1, capabilities=[read])
```

#### 3.3.2 API-key / manuel fallback (OAuth olmayan entegrasyonlar)

Bazı sağlayıcılar OAuth sunmaz (örn. bazı e-ticaret/SEO araçları, webhook-tabanlı).
Bunlar için **aynı kart, farklı modal**:

```
[Bağla]  →  mode: "api_key"  → modal açılır (sayfada kalır, popup yok):
   ┌────────────────────────────────────────────┐
   │  Trendyol'a Bağlan                          │
   │  Trendyol satıcı panelinden API anahtarı    │
   │  ve secret'inizi alın. [Nasıl alınır? ↗]    │ ← her zaman rehber linki
   │  API Key:    [____________________]         │
   │  API Secret: [____________________]         │
   │  Satıcı ID:  [____________]                 │
   │            [Vazgeç]   [Doğrula ve Bağla]     │
   └────────────────────────────────────────────┘
         → POST /api/v1/integrations/trendyol/connect
            { credentials: {...} }
         → backend: connector.validate_credentials() (canlı test çağrısı),
            başarılıysa Vault.put, durum=connected
         → modal kapanır, kart yeşile döner
```

**Sürtünme azaltma:** Her manuel entegrasyon için **"Nasıl alınır?"** adım-adım TR
rehberi (modal içinde açılır accordion + ekran görüntülü). API-key girilince **anında
doğrulama** (geçersizse "Anahtar reddedildi, tekrar deneyin" — sessiz kayıt yok).

### 3.4 Bağlantı Sihirbazı (Onboarding — "ilk veri + ilk aksiyon" dakikalar içinde)

Mevcut `/onboarding` checklist'ini (`onboarding/page.tsx`) **akıllı bağlama
sihirbazına** evriltiyoruz. Yeni kullanıcı `/onboarding` veya ilk `/integrations`
ziyaretinde:

**Adım 0 — Sektör/hedef tespiti (1 ekran, 2 tık):**
```
"AYAZ'ı en hızlı kurmanız için: ne yapıyorsunuz?"
[ ] E-ticaret  [ ] Lead/Hizmet  [ ] Ajans  [ ] Marka
"Reklam veriyor musunuz?" [ ] Evet, hangileri: Google ▣  Meta ▣  TikTok □
```
Bu yanıtlar **önerilen entegrasyon setini** belirler (örn. e-ticaret → Google
Workspace + Meta + Trendyol + GA4 + Slack).

**Adım 1 — Tek-akış bağlama:** Sihirbaz önerilen kartları sırayla gösterir; her biri
3.3'teki popup akışı. "Hepsini Bağla*" düğmesi önerilenleri sırayla popup'lar (kullanıcı
her birinde sadece "izin ver"e basar). Bağlandıkça checklist otomatik dolar.

**Adım 2 — İlk değer anı:** En az 1 reklam/analitik bağlanınca → "İlk veriniz
çekiliyor…" (sync), bitince → "Panele git, verini gör" CTA + Copilot baloncuğu:
*"Slack'inizi de bağladınız — istediğinizde 'ROAS düşerse Slack'e haber ver' diyebilirsiniz."*
Bu, veri→aksiyon köprüsünü ilk dakikada gösterir.

**İlerleme & teşvik:** Mevcut `ProgressHero` + `encouragingLine()` deseni
(`onboarding/page.tsx:15`) korunur; checklist artık dinamik (öneri setine göre).

**Empty/zero state:** Hiç bağlantı yokken `/dashboard`, `/integrations` ve Copilot
**aynı CTA'ya** yönlendirir: "Başlamak için Google veya Meta hesabınızı bağlayın
(2 tık)." Mevcut `DashboardEmptyState.tsx` ve `GettingStarted.tsx` bileşenleri
buna kancalanır.

### 3.5 Bağlantı-sonrası: durum, sağlık, yeniden bağlama

`/connections` "Bağlı Hesaplarım" görünümü her bağlantı için:

| Alan | Kaynak | Görsel |
|---|---|---|
| Durum | `IntegrationConnection.status` | Rozet: **Bağlı** (yeşil) / **Yenileme gerekli** (amber) / **Senkronize ediliyor** (mavi, animasyonlu) / **Hata** (kırmızı) |
| Son senkron | `watermark` / `last_synced_at` | "2 dk önce" (TR relative time) |
| İzinler (scopes) | `IntegrationConnection.scopes` | "Görüntülenen izinler" accordion — kullanıcı tam olarak ne verdiğini görür (KVKK şeffaflık) |
| Sağlık | `last_health_check` + son sync sonucu | Yeşil/amber/kırmızı nokta; "Token 5 gün sonra yenilenecek" |
| Bağlayan | `connected_by_user_id` + `provider_user_email` | "Ayşe (ayse@firma.com) tarafından bağlandı" |

**Aksiyonlar:** **Yeniden Bağla** (token expired/revoked → aynı popup akışı),
**Kaldır** (token revoke + Vault.delete + connection sil — ADR-8 audit'e yazılır),
**Şimdi Senkronize Et** (manuel sync tetikle).

**"Yenileme gerekli" durumu** kritik: refresh job 401 alırsa connection'ı bu duruma
çeker, müşteriye bildirim gönderir, kart amber olur, **tek tık yeniden bağlama**
sunulur. Sürtünmesiz iyileşme.

---

## 4. MİMARİ KALDIRAÇ: PLATFORMA-AİT OAUTH UYGULAMALARI

> Müşteri asla `client_id/secret` girmez. Bu, North Star'ın olmazsa olmazı.
> İyi haber: broker **zaten** bu modelde (`oauth_broker._credentials_for()` →
> `settings`'ten okur). Bu bölüm onu üretime sertleştirir + genişletir.

### 4.1 Operatör-config (sağlayıcı başına bir kez) vs Müşteri-akışı (tık başına)

| | Operatör (AYAZ ekibi, bir kez) | Müşteri (her tık) |
|---|---|---|
| Ne yapar | Sağlayıcının developer console'unda AYAZ OAuth app'i kaydeder; `client_id/secret`'i AYAZ secret store'a (env/Vault) koyar; redirect URI'leri whitelist'ler; gerekli scope'ları/app-review'ı tamamlar | "Bağla" → "İzin Ver" |
| Nerede | `settings` (env: `GOOGLE_CLIENT_ID`, `META_APP_ID`, ...); `oauth_broker._PLATFORM_CONFIGS` | Tarayıcı popup |
| Sıklık | Sağlayıcı başına 1 kez (+ scope değişince) | Entegrasyon başına 1 kez |
| Risk | App-review gecikmesi (Meta/Google hassas scope), redirect URI uyumu | Yok (kimlik girmiyor) |

**Yeni gereksinim:** `_PLATFORM_CONFIGS` artık 3 sağlayıcıyı (`google*`, `meta`,
`tiktok`) kapsıyor. Faz planına göre genişletilecek (LinkedIn, Slack, Google
Workspace bundle, Meta genişletilmiş scope'lar, X, Pinterest). Her ekleme:
`_PlatformOAuthConfig` + `settings`'e credential alanı + redirect URI whitelist.

### 4.2 White-label consent

Mümkün olan yerlerde (Google "OAuth consent screen" branding, Meta app adı/logo)
consent ekranında **"AYAZ"** ve logosu görünür → müşteri güveni. Bazı sağlayıcılar
(LinkedIn) sınırlı branding sunar. Ajans white-label (Agency planı, `Tenant.brand_name`)
**uygulama içi** yüzeyde tam; sağlayıcı consent ekranı AYAZ markalı kalır (sağlayıcı
kısıtı — net belgelenir).

### 4.3 Token yaşam döngüsü (eksik parçanın inşası)

```
authorize → consent → callback → exchange_code → Vault.put(grant)        [VAR]
                                                       │
                                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  Celery beat: refresh_due_grants (her 15 dk)                    │ ← YENİ (tasks/)
   │   - expires_at - now < 10 dk olan grant'leri bul               │
   │   - oauth_broker.refresh(provider, refresh_token)              │  [refresh() VAR]
   │   - Vault.put(yeni token); expires_at güncelle                 │
   │   - 401/invalid_grant → connection.status = "reauth_required"  │
   │       + müşteriye bildirim (notifications_center)              │
   └───────────────────────────────────────────────────────────────┘
   (Mevcut beat schedule'da sadece: saatlik sync, günlük otomasyon, günlük brifing —
    `tasks/celery_app.py`. Token-refresh beat'i YOK; bu, eklenecek tek job.)
   disconnect → oauth_broker.revoke(provider, token) + Vault.delete   ← YENİ (revoke())
```

**En küçük-yetki (least-privilege):** Scope'lar entegrasyon adaptöründe (metadata)
en dar olacak şekilde tanımlanır. Örn. GA4 `analytics.readonly` (readonly, yazma
değil). Search Console `webmasters.readonly`. Sadece gerçekten yazma gereken
entegrasyonlar yazma scope'u ister (Meta `ads_management`, Slack `chat:write`).
Scope'lar `IntegrationConnection.scopes`'a kaydedilir → 3.5'te müşteriye gösterilir.

---

## 5. BİRLEŞİK ADAPTÖR MODELİ (veri OKUMA + aksiyon YAZMA)

> Hedef: **bir geliştirici < 1 günde yeni entegrasyon ekler.** Tek arayüz, tek
> kayıt, tek metadata bloğu hem veri kaynağı hem Copilot aracı doğurur.

### 5.1 Tasarım kararı: mevcut `Connector` ABC'yi GENİŞLET, yeni `Integration` çatısı ekle

Mevcut `Connector` (reklam/analitik OKUMA) sağlam ve sync motoruna bağlı —
**bozmayız.** Onun üstüne, hem OKUMA hem YAZMA hem metadata/Copilot kaydını
birleştiren **`Integration` adaptörü** geliriz. Reklam connector'ları `Integration`'ı
`Connector`'ı sararak (adapter pattern) sunar; saf aksiyon entegrasyonları (Slack)
sadece `Integration`'ı implemente eder.

```python
# backend/ayaz/integrations/base.py  (YENİ)
from __future__ import annotations
import abc
from dataclasses import dataclass, field
from enum import Enum

class AuthType(str, Enum):
    oauth2 = "oauth2"
    oauth2_bundle = "oauth2_bundle"   # tek grant → çok ürün (Google/Meta)
    api_key = "api_key"
    none = "none"

class Capability(str, Enum):
    read = "read"      # veri kaynağı (sync) — fact_daily_metrics / feeds'e besler
    action = "action"  # Copilot/otomasyon yazma aksiyonu

@dataclass(frozen=True)
class ActionSpec:
    """Bir yazma aksiyonu = bir Copilot aracı. TOOL_SPECS'e otomatik dönüşür."""
    name: str                      # ör. "slack_send_message"
    description_tr: str            # Claude'a verilen Türkçe açıklama
    input_schema: dict             # JSON Schema (Claude tool input_schema)
    is_write: bool = True          # True → onay-öncesi + audit (ADR-8)
    required_scopes: tuple[str, ...] = ()

@dataclass(frozen=True)
class IntegrationMetadata:
    key: str                       # "slack", "google_sheets", "google_ads"
    display_name: str              # "Slack"
    category: str                  # "messaging" | "ads" | "analytics" | "social" | "ecommerce" | "productivity"
    description_tr: str
    auth_type: AuthType
    provider: str                  # OAuth provider key (broker'da); bundle ise paylaşılır
    oauth_scopes: tuple[str, ...] = ()
    capabilities: tuple[Capability, ...] = (Capability.read,)
    icon: str = ""                 # tek harf/emoji veya asset key
    icon_bg: str = "#6b7280"
    aliases: tuple[str, ...] = ()  # arama için ("analitik", "bildirim"...)
    setup_guide_url: str = ""      # api_key entegrasyonları için "Nasıl alınır?"
    coming_soon: bool = False
    min_plan: str = "free"         # billing gate (free|starter|growth|agency)

class Integration(abc.ABC):
    metadata: IntegrationMetadata          # sınıf attribute

    def __init_subclass__(cls, **kw):       # OTOMATIK KAYIT (Connector ile aynı desen)
        super().__init_subclass__(**kw)
        if getattr(cls, "metadata", None):
            from ayaz.integrations.registry import IntegrationRegistry
            IntegrationRegistry.register(cls.metadata.key, cls)

    # ── Kimlik (auth_type'a göre biri) ──────────────────────────────
    def validate_credentials(self, creds: dict) -> dict:
        """api_key entegrasyonları: canlı doğrula, normalize edilmiş secret döndür."""
        raise NotImplementedError

    # ── OKUMA tarafı (Capability.read ise) ──────────────────────────
    def as_connector(self, cfg) -> "Connector | None":
        """Mevcut sync motoruna besleyen Connector'ı döndürür (sarmalar)."""
        return None

    # ── YAZMA tarafı (Capability.action ise) ─────────────────────────
    def actions(self) -> list[ActionSpec]:
        """Bu entegrasyonun sunduğu yazma aksiyonları (Copilot araçları)."""
        return []

    def execute_action(self, name: str, args: dict, *, ctx: "ActionContext") -> dict:
        """Tek bir aksiyonu çalıştır. ctx token'ı Vault'tan getirir + audit yazar."""
        raise NotImplementedError

    # ── Keşif (bağlantı sonrası) ──────────────────────────────────────
    def discover(self, ctx: "ActionContext") -> list[dict]:
        """Erişilebilir hesap/entity listesi (çok-hesap seçimi için)."""
        return []
```

**Neden bu işe yarıyor:** Yeni entegrasyon = 1 dosya (`integrations/slack.py`),
1 `IntegrationMetadata` bloğu, gerekirse `as_connector` (OKUMA) ve/veya `actions()` +
`execute_action()` (YAZMA). `__init_subclass__` otomatik kaydeder. Katalog, OAuth
config referansı, billing gate, Copilot araçları — **hepsi metadata'dan türetilir.**

### 5.2 Registry + otomatik çift kayıt

```python
# backend/ayaz/integrations/registry.py (YENİ — Connector registry'nin kardeşi)
class IntegrationRegistry:
    _reg: dict[str, type[Integration]] = {}
    @classmethod
    def register(cls, key, klass): cls._reg[key] = klass
    @classmethod
    def get(cls, key) -> type[Integration]: return cls._reg[key]
    @classmethod
    def all(cls) -> list[type[Integration]]: return list(cls._reg.values())
    @classmethod
    def catalog(cls) -> list[IntegrationMetadata]:
        return [k.metadata for k in cls._reg.values()]
    @classmethod
    def action_specs_for(cls, connected_keys: set[str]) -> list[dict]:
        """Bağlı entegrasyonların aksiyonlarını Claude TOOL_SPECS formatında döndürür."""
        specs = []
        for k in connected_keys:
            inst = cls._reg[k]()                       # type: ignore
            for a in inst.actions():
                specs.append({
                    "name": a.name,
                    "description": a.description_tr,
                    "input_schema": a.input_schema,
                    "is_action": a.is_write,
                })
        return specs
```

**Kayıt yolu:** `ayaz/integrations/__init__.py` her modülü import eder (Connector
deseniyle aynı) → `__init_subclass__` tetiklenir → registry dolu. Tek import,
hem katalog hem Copilot araç havuzu hazır.

### 5.3 Somut örnek adaptörler

#### (a) Slack — saf aksiyon entegrasyonu (YAZMA)

```python
# backend/ayaz/integrations/slack.py
class SlackIntegration(Integration):
    metadata = IntegrationMetadata(
        key="slack", display_name="Slack", category="messaging",
        description_tr="Performans uyarılarını ve raporları Slack kanalına gönderin.",
        auth_type=AuthType.oauth2, provider="slack",
        oauth_scopes=("chat:write", "channels:read"),
        capabilities=(Capability.action,),
        icon="#", icon_bg="#4A154B",
        aliases=("bildirim", "mesaj", "uyarı kanalı"),
        min_plan="growth",          # billing gate: Slack Growth+ (PLANS.alerts_slack ile uyumlu)
    )
    def actions(self):
        return [ActionSpec(
            name="slack_send_message",
            description_tr=("[EYLEM] Belirtilen Slack kanalına mesaj gönderir. "
                            "Kullanıcı 'Slack'e gönder/bildir' dediğinde kullan."),
            input_schema={"type":"object","properties":{
                "channel":{"type":"string","description":"Kanal adı, ör. #pazarlama"},
                "text":{"type":"string","description":"Gönderilecek mesaj"}},
                "required":["channel","text"]},
            is_write=True, required_scopes=("chat:write",))]
    def execute_action(self, name, args, *, ctx):
        token = ctx.vault_get()["access_token"]          # per-tenant token
        # httpx POST https://slack.com/api/chat.postMessage ...
        return {"sent": True, "channel": args["channel"]}
```

#### (b) Google Sheets — aksiyon (export YAZMA) + bundle parçası

```python
class GoogleSheetsIntegration(Integration):
    metadata = IntegrationMetadata(
        key="google_sheets", display_name="Google Sheets", category="productivity",
        description_tr="Rapor ve metrikleri Google E-Tablolar'a aktarın.",
        auth_type=AuthType.oauth2_bundle, provider="google_workspace",
        oauth_scopes=("https://www.googleapis.com/auth/spreadsheets",),
        capabilities=(Capability.action,), icon="S", icon_bg="#0F9D58",
        aliases=("e-tablo","excel","sheets","rapor aktar"), min_plan="starter")
    def actions(self):
        return [ActionSpec(
            name="gsheets_export_report",
            description_tr="[EYLEM] Seçili dönem performansını yeni bir Google E-Tablo'ya aktarır.",
            input_schema={"type":"object","properties":{
                "title":{"type":"string"},
                "date_from":{"type":"string"},"date_to":{"type":"string"}},
                "required":["title","date_from","date_to"]},
            is_write=True)]
    # execute_action: get_performance_summary tool'unu çağır → Sheets API'ye yaz
```

#### (c) Google Ads — OKUMA, mevcut Connector'ı sarmalar (sıfır yeniden yazım)

```python
class GoogleAdsIntegration(Integration):
    metadata = IntegrationMetadata(
        key="google_ads", display_name="Google Ads", category="ads",
        description_tr="Arama ve görüntülü reklam performansı.",
        auth_type=AuthType.oauth2_bundle, provider="google_workspace",
        oauth_scopes=("https://www.googleapis.com/auth/adwords",),
        capabilities=(Capability.read,), icon="G", icon_bg="#4285F4",
        aliases=("google reklam","arama reklamı","sem"), min_plan="free")
    def as_connector(self, cfg):
        from ayaz.connectors.registry import ConnectorRegistry
        return ConnectorRegistry.get("google_ads")(cfg)   # mevcut connector aynen
```

> Üç örnek üç deseni kapsar: **saf aksiyon** (Slack), **aksiyon+bundle** (Sheets),
> **mevcut OKUMA connector sarmalama** (Google Ads). Yeni entegrasyon eklemek =
> bu üçünden birini kopyalamak.

### 5.4 Aksiyon yürütme bağlamı (`ActionContext`)

```python
@dataclass
class ActionContext:
    tenant_id: uuid.UUID
    connection_id: uuid.UUID
    user_id: uuid.UUID
    db: Session
    vault: SecretsVault
    def vault_get(self) -> dict:   # token'ı grant ref'inden çöz
        ...
    def audit(self, action, args, result, status): ...   # ADR-8 audit log
```

Her `execute_action` `ActionContext` alır → token erişimi, audit, tenant-scope tek
yerde. Adaptör yazarı güvenlik/izolasyon detaylarıyla uğraşmaz.

---

## 6. COPILOT AKSİYON BAĞLANTISI ("Veriye Sor" / AI Asistanı)

> Mevcut: `TOOL_SPECS` statik liste, her tenant aynı; `dispatch()` sabit
> `_TOOLS` tablosu (`copilot_tools.py`). Yeni: bağlantı-farkında, per-tenant
> dinamik araç havuzu.

### 6.1 Dinamik, per-tenant araç havuzu

```
chat() çağrısı (copilot.py)   — API: POST /api/v1/assistant/conversations/{id}/messages
   │
   ├─ static_tools = TOOL_SPECS                       (mevcut 20 okuma + 2 aksiyon aracı)
   ├─ connected = IntegrationConnection bağlı keys (tenant)
   ├─ integration_tools = IntegrationRegistry.action_specs_for(connected)   ← YENİ
   ├─ tools = static_tools + integration_tools  (plan/scope ile filtrele)
   └─ _call_claude(..., tools=tools)
```

> Mevcut `_call_claude` (`copilot.py:937`) `tools=TOOL_SPECS`'i **doğrudan** import
> ediyor. Tek değişiklik: `chat()` araç listesini dinamik kurup `_call_claude`'a
> parametre olarak geçirir. Stub path (`_stub_chat`) ve `dispatch` aynı dinamik
> havuzu kullanır. UI tarafı hazır: `QuickAsk.tsx` + `/assistant` chat ekranı zaten
> `tools_used` rozetlerini ("aksiyon" çipleri) gösteriyor — entegrasyon aksiyonları
> aynı yüzeyde belirir.

Müşteri **Slack'i bağlamadıysa** Claude `slack_send_message` aracını **görmez** →
halüsinasyon yok, "bağlı değil" hatası yok. Bağladığı an araç belirir. Bu, veri↔aksiyon
birleşik kokpitin özü: *"ROAS %20 düşerse Slack'e haber ver"* sadece Slack bağlıysa
mümkün ve Copilot bunu bilir.

### 6.2 Dispatch genişletmesi

`copilot_tools.dispatch()` önce `_TOOLS`'a bakar; bulamazsa
`IntegrationRegistry`'den entegrasyon aksiyonuna yönlendirir:

```python
def dispatch(name, db, tenant_id, args, *, user_id=None, vault=None):
    fn = _TOOLS.get(name)
    if fn: return fn(db=db, tenant_id=tenant_id, **args)
    # entegrasyon aksiyonu mu?
    integ = IntegrationRegistry.find_by_action(name)      # YENİ
    if integ:
        conn = _resolve_connection(db, tenant_id, integ.metadata.key)
        if conn is None:
            return {"error": f"{integ.metadata.display_name} bağlı değil."}
        ctx = ActionContext(tenant_id, conn.id, user_id, db, vault)
        return integ().execute_action(name, args, ctx=ctx)
    return {"error": f"Bilinmeyen araç: {name!r}"}
```

### 6.3 Yetkilendirme, onay-öncesi, oto vs co-pilot (ADR-8)

| Katman | Kural |
|---|---|
| **Per-action yetki** | `ActionSpec.required_scopes` connection'ın `scopes`'unda yoksa → reddet, "yetki yetersiz, yeniden bağlayın". Yazma aksiyonu için üyelik rolü `owner/admin` (member salt-okunur — `MembershipRole`) |
| **Onay-öncesi (confirm-before-write)** | `is_write=True` aksiyonlar **iki-fazlı**: Copilot önce `{preview: ..., requires_confirmation: true}` döndürür → UI "Onayla/İptal" gösterir → kullanıcı onaylar → asıl yürütme. `create_automation_rule`'daki mevcut "TASLAK" deseninin genelleştirilmesi |
| **Oto vs co-pilot** | Varsayılan **co-pilot** (her yazma kullanıcı onayı). Otomasyon kuralları (`automation`) üzerinden kullanıcı **önceden** "oto" yetkisi verirse (örn. "ROAS düşerse otomatik Slack") → audit'li otomatik yürütme. Geri alınamaz/parasal aksiyonlar (bütçe değiştir, reklam durdur) **asla** oto değil |
| **Audit** | Her yazma `action_audit_log`'a yazılır (kim, ne, ne zaman, args, sonuç, onay durumu) — KVKK + güven |

Sistem prompt'una (`copilot.py:_SYSTEM_PROMPT`) eklenecek kural: *"Yazma aksiyonu
araçlarını yalnızca kullanıcı açıkça istediğinde çağır; çağırmadan önce ne
yapacağını özetle ve onay iste."* (Mevcut prompt zaten bu deseni
`create_automation_rule/create_goal` için içeriyor — genişletilir.)

---

## 7. VERİ MODELİ + API

### 7.1 Yeni / değişen tablolar

Mevcut `ConnectedAccount` (reklam/analitik OKUMA, sync motoruna bağlı) **olduğu gibi
kalır.** Birleşik entegrasyon yaşam döngüsü için yeni tablolar (Alembic `0027+`):

```
provider_grants                       (YENİ) — bir OAuth grant = bir Vault kaydı
  id PK
  tenant_id FK→tenants            (index, RLS)
  provider              str        # "google_workspace","meta","slack","tiktok"
  vault_secret_ref      text       # enc:... (Fernet) — TOKEN BURADA DEĞİL, Vault'ta
  provider_user_email   str|null   # "ayse@firma.com" (hangi hesapla bağlandı)
  scopes                json       # verilen scope listesi
  access_expires_at     timestamptz|null
  connected_by_user_id  FK→users
  status                str        # active | reauth_required | revoked
  created_at, updated_at

integration_connections              (YENİ) — bir entegrasyon örneği (grant'i paylaşabilir)
  id PK
  tenant_id FK→tenants            (index, RLS)
  integration_key       str        # "google_ads","slack","trendyol" (metadata.key)
  provider_grant_id     FK→provider_grants  (bundle: çok connection tek grant)
  external_entity_id    str        # seçilen hesap/property/kanal
  display_name          str
  capabilities          json       # ["read"] / ["action"] / ["read","action"]
  status                str        # connected | syncing | reauth_required | error | disabled
  scopes                json
  last_synced_at        timestamptz|null
  last_health_check     timestamptz|null
  watermark             text|null  # incremental sync (ConnectedAccount ile uyumlu)
  created_at, updated_at
  UNIQUE(tenant_id, integration_key, external_entity_id)

action_audit_log                     (YENİ) — ADR-8 yazma denetim izi
  id PK
  tenant_id FK→tenants            (index, RLS)
  connection_id FK→integration_connections
  user_id FK→users
  action_name           str
  args_redacted         json       # PII/secret maskeli
  result_status         str        # ok | error | denied
  result_summary        str
  was_auto              bool       # oto mu, co-pilot mı
  created_at            timestamptz (index)

integration_requests                 (YENİ, opsiyonel) — "Yakında" kartı "Haber ver"
  id PK, tenant_id, integration_key, requested_by, created_at
```

**Vault saklama:** Token'lar `provider_grants.vault_secret_ref`'e Fernet ile
şifrelenir — mevcut `EncryptedColumnVault` deseniyle aynı (`vault.py`). `ref` =
`provider_grant.id`. Reklam connector'larının `ConnectedAccount.vault_secret_ref`
yolu da çalışmaya devam eder; köprü servisi grant'i her ikisine de bağlar.

**`Platform` enum genişletme:** `oltp.py:Platform`'a aksiyon platformları
(`slack`, `google_sheets`, `gmail`, `whatsapp`, `instagram`, `facebook_page`,
`x`, `trendyol`, `hepsiburada`) eklenir VEYA — daha temiz — `integration_key`
serbest string olur ve `Platform` enum'u yalnızca reklam/analitik OKUMA için kalır.
**Öneri: `integration_key` string** (katalog metadata'dan doğrulanır), enum'u
şişirmemek için.

### 7.2 Ana endpoint'ler (yeni router: `api/v1/integrations.py`)

```
GET    /api/v1/integrations                 → katalog (metadata + bu tenant'ın bağlı durumu)
                                              query: ?category=&status=&q=
GET    /api/v1/integrations/recommended      → onboarding sektör cevabına göre öneri seti
POST   /api/v1/integrations/{key}/connect    → {authorize_url, connection_id, mode}  (oauth|api_key)
                                              (mevcut /oauth/{provider}/authorize'ı sarar)
POST   /api/v1/integrations/{key}/credentials→ api_key fallback: doğrula+Vault.put
GET    /api/v1/integrations/connections      → bağlı connection listesi (sağlık dahil)
POST   /api/v1/integrations/connections/{id}/sync     → manuel sync
POST   /api/v1/integrations/connections/{id}/reconnect→ yeniden bağla (yeni authorize_url)
DELETE /api/v1/integrations/connections/{id} → revoke + Vault.delete + audit
GET    /api/v1/integrations/{key}/discover    → bağlantı sonrası hesap/entity seçimi
POST   /api/v1/integrations/requests          → "Yakında" talep sinyali

# Mevcut, korunur:
GET    /api/v1/oauth/{provider}/authorize     (oltp.py mevcut — provider'lı genişletilir)
GET    /api/v1/oauth/{provider}/callback      (popup postMessage HTML döndürecek şekilde güncellenir)
GET    /api/v1/connectors/...                 (geriye uyumluluk; /integrations'a köprülenir)
```

### 7.3 Multi-tenant izolasyon

- Her yeni tablo `tenant_id` taşır (mevcut RLS-hazır desen, `oltp.py` yorumları).
  Mevcut veri modelinde **33 tenant-scoped model** zaten bu deseni izliyor; yeni
  tablolar aynı kalıba uyar.
- Her endpoint `get_current_membership` ile tenant'ı çözer (`api/deps.py:113`):
  tenant JWT `tid` claim'inden gelir, membership doğrulanır. Her sorgu `tenant_id`
  filtreli (RLS aktifleşene dek — mevcut konvansiyon).
- Aksiyon entegrasyonu billing gate'i: mevcut `require_within_data_source_limit`
  (`billing.py:257`) reklam/analitik OKUMA için `max_data_sources`'u sayar. Aksiyon
  entegrasyonları **`min_plan` metadata'sı** ile ayrı gate'lenir (Slack→growth,
  Sheets→starter) — `PLANS` feature flag'leriyle (`alerts_slack` vb.) hizalı.
- OAuth `state` token'ı tenant+connection bağlar; callback tenant eşleşmesini
  doğrular (mevcut `oauth.py` deseni). **İyileştirme:** `state`'i HMAC-imzala
  (mevcut `_sign_state` sadece base64; broker docstring'i bunu kabul ediyor) +
  PKCE ekle.
- Copilot araçları **her zaman** `tenant_id` forward eder (mevcut garanti,
  `copilot_tools.dispatch`).

---

## 8. KVKK / GÜVENLİK (Composio'ya karşı ASIL farklılaştırıcı)

| Gereksinim | Tasarım | Mevcut temel |
|---|---|---|
| **Token'lar AYAZ'da, 3. taraf broker yok** | Tüm token/secret AYAZ Vault'unda (Fernet AES-128-CBC+HMAC), TR/EU ikametgâhında. Composio gibi 3. taraf token deposu **yok** → sınır ötesi transfer yok | `vault.py` `EncryptedColumnVault` |
| **Per-tenant şifreleme** | `vault_secret_ref` tenant satırına bağlı; `tenant_id` her grant'te. Üretimde KMS-destekli per-tenant anahtar opsiyonu (DEK/KEK) — Faz 3 sertleştirme | PBKDF2→Fernet (`_derive_fernet_key`) |
| **En az yetki (least-privilege)** | Scope'lar adaptör metadata'sında dar; readonly varsayılan; yazma scope'u sadece gerektiğinde | `oauth_broker` GA4/SC readonly scope'lar |
| **Rıza kayıtları** | Her grant: verilen scope + zaman + bağlayan kullanıcı + provider email → `provider_grants`. KVKK Rıza Merkezi'ne (`/consent`) bağlanabilir | `Tenant.kvkk_region`, mevcut consent modülü |
| **Audit izi** | Her yazma aksiyonu `action_audit_log`'a (kim/ne/ne zaman/sonuç/onay). Bağlama/kaldırma da loglanır | mevcut `services/audit.py` deseni |
| **Per-action yetki** | scope + rol (`owner/admin`) kontrolü; member yazma yapamaz | `MembershipRole` enum |
| **Şifreleme (transit/rest)** | Transit HTTPS (proxy CA); rest Fernet. Secret'lar loglanmaz (mevcut `oauth.py` callback raw exception'ı gizliyor — bu konvansiyon korunur) | `oauth.py:259` exception redaction |
| **Token revocation** | Disconnect → `oauth_broker.revoke()` (YENİ) + `Vault.delete()` + connection sil + audit. Sağlayıcıda da iptal | `vault.delete()` VAR; `revoke()` eklenecek |
| **PII redaction** | Audit args'ında e-posta/telefon/mesaj içeriği maskelenir (`args_redacted`) | — (yeni) |

**Pazarlama mesajı (ürün konumlandırma):** *"Anahtarlarınız Türkiye'de, AYAZ'ın
kasasında. Composio gibi verilerinizi yurtdışı bir aracıya emanet etmezsiniz."*
Bu, TR ICP için somut bir satın-alma sebebi (KVKK uyum + güven).

---

## 9. KATALOG KAPSAMI & FAZLAMA

> **Net duruş:** Composio'nun 500+ entegrasyonunu **kovalamıyoruz.** TR-ICP için
> küratörlü ~25 entegrasyon + talep-güdümlü genişleme (`integration_requests`
> sinyaliyle önceliklendirme). Kalite ve "her biri gerçekten çalışıyor" > genişlik.

### Faz 1 — Çekirdek reklam/analitik OKUMA (mevcut motoru birleşik UX'e bağla)
Zaten connector'ı VAR; sadece `Integration` sarmalama + yeni katalog UX + bundle:
- **Google Workspace bundle** (tek consent): Google Ads + GA4 + Search Console
- **Meta Ads**, **TikTok Ads**, **LinkedIn Ads**, **Microsoft Ads**
- Çıktı: müşteri 2 tıkla (Google + Meta) en kritik 4 veri kaynağını açar.

### Faz 2 — İlk aksiyon entegrasyonları (veri→aksiyon köprüsü)
- **Slack** (uyarı/rapor gönder) — Growth+
- **Google Sheets** (rapor export) — Starter+
- **Gmail** (rapor/uyarı e-postası) — Google bundle'a eklenir
- Çıktı: Copilot ilk YAZMA araçlarını kazanır; "Slack'e haber ver" çalışır.

### Faz 3 — TR e-ticaret + mesajlaşma (ICP derinleşme)
- **Trendyol**, **Hepsiburada** (api_key fallback; satıcı metrik OKUMA + sipariş)
- **WhatsApp Business** (mesaj/şablon gönder — Meta bundle)
- Çıktı: TR pazaryeri reklamvereni/e-ticaretçi tam kapsanır (rakiplerde nadir).

### Faz 4 — Sosyal yayın + genişleme (kimlik-ağır, app-review gerekli)
- Sosyal publish: **Instagram, Facebook Page, X, LinkedIn, TikTok** (içerik yayını —
  mevcut `content` modülüyle birleşir; her ağ app-review ister)
- Talep-güdümlü ekler (`integration_requests` top-N): örn. **Shopify, İdeasoft,
  T-Soft, HubSpot**

| Entegrasyon | Faz | Yetenek | Auth | Min plan | Not |
|---|---|---|---|---|---|
| Google Ads | 1 | read | oauth bundle | free | connector VAR |
| GA4 | 1 | read | oauth bundle | free | connector VAR |
| Search Console | 1 | read | oauth bundle | free | connector VAR |
| Meta Ads | 1 | read | oauth | free | connector VAR |
| TikTok Ads | 1 | read | oauth | starter | connector VAR |
| LinkedIn Ads | 1 | read | oauth | growth | connector VAR |
| Microsoft Ads | 1 | read | oauth | growth | connector VAR |
| Slack | 2 | action | oauth | growth | YENİ |
| Google Sheets | 2 | action | oauth bundle | starter | YENİ |
| Gmail | 2 | action | oauth bundle | starter | YENİ |
| Trendyol | 3 | read+action | api_key | growth | YENİ |
| Hepsiburada | 3 | read+action | api_key | growth | YENİ |
| WhatsApp Business | 3 | action | oauth (Meta) | growth | YENİ, app-review |
| Instagram (publish) | 4 | action | oauth (Meta) | growth | app-review |
| Facebook Page (publish) | 4 | action | oauth (Meta) | growth | app-review |
| X (publish) | 4 | action | oauth | growth | app-review |
| LinkedIn (publish) | 4 | action | oauth | growth | app-review |
| TikTok (publish) | 4 | action | oauth | growth | app-review |

(~18 isimli + talep-güdümlü 5-7 = hedef ~25.)

---

## 10. BUILD vs COMPOSIO — dürüst karşılaştırma + öneri

| Boyut | Native (build) | Composio (entegre) |
|---|---|---|
| KVKK / veri ikametgâhı | **Tam kontrol**, token TR/EU'da AYAZ Vault'unda | Token 3. tarafta, sınır ötesi → KVKK riski/belirsizlik |
| Maliyet | Öngörülebilir (altyapı + bakım) | Kullanım-başı, ölçeklenince öngörülemez |
| "Tek çatı" moat | Entegrasyon + birleşik veri + Copilot **tek üründe** → kopyalanması zor | Composio değiştirilebilir bir bağımlılık; moat zayıf |
| Genişlik | Curated ~25 (talep-güdümlü) | 500+ hazır |
| Time-to-market | Daha yavaş (her entegrasyon emek) | Hızlı (hazır connector) |
| Bakım yükü | **Bizde** (API değişimi, token, rate-limit) | Composio'da |
| Mevcut temel | **%70 hazır** (broker+vault+registry+tool layer) | Hazırı atıp dış bağımlılığa geçmek israf |

**Öneri (net): BUILD.** Üç sebep dominant:
1. **KVKK farklılaştırıcısı** — TR ICP için somut satın-alma sebebi; Composio bunu veremez.
2. **Temel zaten var** — broker, Vault, registry, Copilot tool layer olgun;
   Composio'ya geçmek mevcut yatırımı çöpe atar.
3. **Moat** — birleşik veri+aksiyon+Copilot tek üründe; entegrasyon katmanını
   dışarı vermek ürünün kalbini kiralamak olur.

**Kabul edilen takas:** Genişlikten feragat ve bakım yükünü üstleniriz. Bunu
**curated + talep-güdümlü** katalog ile yönetiriz — 500 değil, doğru 25.

---

## 11. UYGULAMA YOL HARİTASI (mühendisliğe iş kalemleri)

**Sprint 1 — Çatı (integrations-engineer + backend-engineer):**
- `ayaz/integrations/{base,registry,__init__}.py` (`Integration` ABC + registry)
- 7 mevcut connector için `Integration` sarmalayıcı metadata (OKUMA)
- `provider_grants` + `integration_connections` tabloları (Alembic `0027`)
- `oauth_broker`: `google_workspace` bundle config + `revoke()` + PKCE + HMAC state
- `api/v1/integrations.py` katalog + connect + connections endpoint'leri

**Sprint 2 — Müşteri UX (frontend-engineer + ux-designer):**
- `/integrations` Entegrasyon Merkezi (katalog, arama, kategori, 3-state kart)
- `IntegrationCard` bileşeni (globals.css token'ları)
- Popup + postMessage OAuth akışı; callback HTML (`oauth.py` güncelle)
- `/connections` "Bağlı Hesaplarım" sağlık/scope/yeniden-bağla görünümü
- Bağlantı Sihirbazı (`/onboarding` evrim — sektör tespiti + tek-akış bağla)

**Sprint 3 — Aksiyon + Copilot (integrations-engineer + backend-engineer):**
- Slack + Google Sheets + Gmail adaptörleri (`actions()` + `execute_action`)
- `action_audit_log` tablosu + `ActionContext`
- `copilot.py`/`copilot_tools.py`: dinamik per-tenant araç havuzu + dispatch köprüsü
- Onay-öncesi (iki-fazlı) yazma akışı (UI + backend)
- Token refresh Celery beat job (`tasks/`)

**Sprint 4 — TR e-ticaret + sertleştirme (integrations + security-compliance):**
- Trendyol/Hepsiburada (api_key) + WhatsApp
- KVKK rıza kaydı UI (`/consent` entegrasyonu), PII redaction, security review
- Billing: aksiyon entegrasyonu gate'leri (`min_plan`)

---

## 12. RİSKLER

| Risk | Etki | Azaltma |
|---|---|---|
| Meta/Google **app-review** (hassas scope, özellikle yazma/publish) | Faz 4 gecikir | Readonly scope'lar review gerektirmez (Faz 1 hızlı); yazma/publish için erken başvuru |
| `SyncStatus` backend↔frontend uyumsuzluğu (`idle/success` vs `connected/pending`) | Yanlış rozet | Tek vocabulary'ye geç (`integration_connections.status`); frontend map'i (`connectors-api.ts:74`) kaldır |
| Token refresh job yokluğu | Bağlantılar sessizce ölür | Sprint 3 Celery beat; "reauth_required" + bildirim + tek-tık yeniden bağla |
| Vault tek-anahtar (tüm tenant aynı `VAULT_KEY`) | Anahtar sızıntısı = tüm token | Faz 3: KMS DEK/KEK per-tenant; şimdilik `VAULT_KEY` env-only + rotasyon prosedürü |
| Rate-limit (sağlayıcı API) | Sync/aksiyon başarısız | `ConnectorCapabilities.rate_limit_rpm` zaten var; aksiyonlara backoff + retry + dead-letter |
| ToS kısıtları (özellikle scraping/publish) | Hesap askıya alma | Yalnızca resmi API; publish'te platform politikalarına uyum; ToS denetimi entegrasyon-onay sürecine |
| Geri alınamaz aksiyon (bütçe/durdurma oto) | Müşteri zararı | ADR-8: parasal/geri-alınamaz aksiyonlar asla oto; her zaman co-pilot onay |

---

## 13. EK — İLGİLİ DOSYA REFERANSLARI (mutlak yollar)

Mevcut (okundu, temel alınacak):
- `/home/user/AYAZ/backend/ayaz/connectors/base.py` — Connector ABC, UnifiedRecord, Capabilities
- `/home/user/AYAZ/backend/ayaz/connectors/registry.py` — auto-register deseni
- `/home/user/AYAZ/backend/ayaz/services/oauth_broker.py` — platforma-ait OAuth (kaldıraç)
- `/home/user/AYAZ/backend/ayaz/services/vault.py` — Fernet per-tenant Vault
- `/home/user/AYAZ/backend/ayaz/api/v1/oauth.py` — authorize/callback (popup'a güncellenecek)
- `/home/user/AYAZ/backend/ayaz/api/v1/connectors.py` — CRUD iskeleti
- `/home/user/AYAZ/backend/ayaz/models/oltp.py` — Tenant/Membership/ConnectedAccount/Platform/SyncStatus
- `/home/user/AYAZ/backend/ayaz/services/copilot.py` — Claude tool-use loop
- `/home/user/AYAZ/backend/ayaz/services/copilot_tools.py` — TOOL_SPECS/dispatch/ACTION_TOOLS
- `/home/user/AYAZ/backend/ayaz/services/billing.py` — entitlements + data-source gate
- `/home/user/AYAZ/frontend/src/app/connections/page.tsx` — mevcut bağlama UI
- `/home/user/AYAZ/frontend/src/app/onboarding/page.tsx` — checklist (sihirbaza evrilecek)
- `/home/user/AYAZ/frontend/src/components/AppNav.tsx` — NAV_GROUPS "Veri & Entegrasyon"
- `/home/user/AYAZ/frontend/src/lib/connectors-api.ts` — API client + SyncStatus map
- `/home/user/AYAZ/frontend/src/app/globals.css` — tasarım token'ları

Yeni (inşa edilecek):
- `/home/user/AYAZ/backend/ayaz/integrations/base.py` — Integration ABC + metadata + ActionSpec
- `/home/user/AYAZ/backend/ayaz/integrations/registry.py` — IntegrationRegistry
- `/home/user/AYAZ/backend/ayaz/integrations/{slack,google_sheets,gmail,trendyol,...}.py`
- `/home/user/AYAZ/backend/ayaz/api/v1/integrations.py` — katalog/connect/connections API
- `/home/user/AYAZ/backend/ayaz/models/integrations.py` — provider_grants, integration_connections, action_audit_log
- `/home/user/AYAZ/backend/alembic/versions/0027_integrations.py`
- `/home/user/AYAZ/backend/ayaz/tasks/token_refresh.py` — refresh beat job
- `/home/user/AYAZ/frontend/src/app/integrations/page.tsx` — Entegrasyon Merkezi
- `/home/user/AYAZ/frontend/src/components/IntegrationCard.tsx`
- `/home/user/AYAZ/frontend/src/lib/integrations-api.ts`
```
