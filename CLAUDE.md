# AYAZ — Claude Code Çalışma Notları

> Bu dosya yeni bir oturumu anında brifinglemek içindir. Proje = kullanıcının
> **"Digital marketing platform startup"** dediği ürün. GitHub: `aieasycep/AYAZ`
> · yerel: `~/AYAZ` · branch: `claude/marketing-platform-startup-ch6zq3`.
> TR-öncelikli, AI'lı dijital pazarlama kokpiti (SaaS).

## Çalışma modeli — Lider + Uzman Ajanlar (ÖNEMLİ)
Sen **takım lideri / orkestratör**sün. `.claude/agents/` altında **11 kalıcı uzman**
var (product-strategist, solution-architect, integrations-engineer, backend-engineer,
frontend-engineer, mobile-engineer, data-analytics-engineer, devops-engineer,
ux-designer, qa-engineer, security-compliance). Ağır işi (araştırma, çok dosya okuma,
deneme-yanılma) **Task/Agent ile bu uzmanlara delege et**; onlar kendi izole
context'lerinde çalışıp yalnızca **karar-hazır özet** döner → ana context yağsız kalır,
kayıplı compaction seyrekleşir. Ana thread'i **sadece kararlara** ayır. Detay:
`docs/00-team-charter.md`.

> Not: Bu 11 kuruluş kadrosu. Cloud oturumunda sonradan dinamik açılan uzmanlar dosyaya
> yazılmadı; gerektiğinde yeni rolü `.claude/agents/`'a kalıcı ajan olarak ekle
> (ör. `growth-marketer`, `content-strategist`).

## Kullanıcı tercihi
- **Otonom çalış**: izin sorma, en doğru kararı ver ve uygula; sorumluluk kullanıcıda.
  (Oturum `bypassPermissions` ile başlar — `.claude/settings.local.json`.)
- **Kapsamlı + özgün UI** iste; minimal değil. "Yapıldı" demeden önce **görsel doğrula**
  (headless/browser ile ekran görüntüsü). Test + gerçek davranışla doğrula.
- TR iş mantığında Türkçe yorum; TR sayı/tarih/₺ biçimi.

## Durum (2026-07-09)
- Yerel `main`/branch **origin ile senkron**, çalışma ağacı temiz.
- Modüller **M1–M10 + 7 farklılaştırıcı** hazır; canlı veri/ödeme/AI müşteri kimlikleri
  bekliyor (yoksa offline mock çalışır). Yol haritası: `docs/05-comprehensive-roadmap.md`,
  geçmiş: `docs/CHANGELOG.md`, kullanıcıdan beklenenler: `docs/06-user-todo.md`.

## Lokal koşma (Docker'sız, SQLite — kurulu ve çalışır)
Python 3.12 venv: `backend/.venv`. `backend/.env` SQLite'a ayarlı (DEBUG=false,
RATE_LIMIT_ENABLED=false). Şema alembic yerine `Base.metadata.create_all` ile kurulur
(modeller cross-dialect GUID). Demo giriş: **demo@ayaz.app / demo12345**.

```bash
# Backend (backend/ dizininden — sqlite göreli yol için):
cd ~/AYAZ/backend && ./.venv/bin/uvicorn ayaz.main:app --host 127.0.0.1 --port 8000
# Şema+seed sıfırdan gerekirse:
#   ./.venv/bin/python -c "import ayaz.main; from ayaz.database import engine; from ayaz.models.base import Base; Base.metadata.create_all(engine)"
#   ./.venv/bin/python -m scripts.seed_demo
# Frontend (:3000, Next 14.2.5 — proje bu sürümde; global Next 15 ile başlatma):
cd ~/AYAZ/frontend && npm run dev
```
Frontend API tabanı `NEXT_PUBLIC_API_BASE` (varsayılan `http://localhost:8000`).
Gerçek Postgres/alembic akışı için `docker-compose.yml` (Postgres 16 + Redis 7).

## Repo not
- Ayrı repo olan `~/digitall` (Turborepo mikroservis monorepo'su) ile KARIŞTIRMA — bu
  ayrı bir kod tabanı (FastAPI monolit + Next.js).
