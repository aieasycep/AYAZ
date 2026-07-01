# AYAZ Final UX Polish Audit — Haziran 2026

**Scope:** Full-app visual audit across all 37 screens at 1440px. Screenshots from `/shots_v2/`. Code reviewed: `globals.css`, `billing.module.css`, `integrations.module.css`, `seo.module.css`, `notifications.module.css`.

**Not in scope:** architecture changes, new dependencies, sidebar redesign, design-system redefinition.

---

## Wave 1 — Global / Shared Quick Wins (touch many screens at once)

### Item 1 — Inconsistent `padding` and `gap` units: raw `rem` vs design tokens (S)

**Screens affected:** billing, notifications, settings, workspaces, connections, ads, dashboard, recommendations — approximately 18 of 37 screens.

**Issue:** The token migration is incomplete. `billing.module.css` uses `1.5rem`, `0.9rem`, `0.875rem`, `1.25rem`, `0.375rem` throughout, instead of `--space-*` and `--text-*`. `notifications.module.css` uses `1rem`, `1.25rem`, `0.75rem`, `0.9375rem`. The visual result is that these screens render with subtly different vertical rhythm from the fully-migrated screens (integrations, seo), which have adopted `var(--space-5)`, `var(--text-sm)`, etc. everywhere. On a 1440px screen the difference is visible when switching between, for example, Notifications and Integrations: the list rows feel slightly tighter, the page-header bottom gap is larger.

**Fix:** Global search-replace in the affected module CSS files. Replace raw rem values with their token equivalents:
- `0.75rem` → `var(--text-xs)` (for labels) or `var(--space-3)` (for gaps)
- `0.875rem` → `var(--text-sm)` / `var(--space-3)`
- `1rem` / `1.25rem` padding → `var(--space-4)` / `var(--space-5)`
- `1.5rem` padding → `var(--space-6)`
- `0.375rem` → `var(--space-1)` or `var(--space-2)`

Run: `grep -r "padding:.*rem\|gap:.*rem\|font-size:.*rem" frontend/src/app/*/` to find all remaining instances. Prioritise billing, notifications, settings, connections. No visual redesign; purely token substitution.

**Effort:** S

---

### Item 2 — Section-header label casing and weight inconsistency across 12+ screens (S)

**Screens affected:** billing (`KAYNAK KULLANIMI`, `PLAN KARŞILAŞTIRMA`), tracking (`HEDEFLER (DESTINATIONS)`, `ZORUNLU RIZA SİNYALLERİ`), connections (`Bağlı Hesaplar`, `Desteklenen Platformlar`), consent, feeds, audit, roles, workspaces, settings.

**Issue:** Section labels above content blocks use at least three different visual styles across the app:
- Style A (correct, from integrations/seo): `font-size: var(--text-xs)`, `font-weight: var(--fw-semibold)`, uppercase, `letter-spacing: 0.6px`, `color: var(--color-text-muted)` — matches `SectionCard` heading pattern.
- Style B (billing, connections): same text but at `--text-sm` or `0.75rem` with lighter weight — appears in ALL CAPS but looks visually heavier.
- Style C (tracking, consent): mixed case with no uppercase at all, at `--text-base`, making them look like body text rather than section dividers.

The result is visual hierarchy confusion: on `tracking.png`, the "HEDEFLER (DESTINATIONS)" label appears to be at the same weight as sub-item labels. On `connections.png`, "Desteklenen Platformlar" is a plain text heading with no visual separation.

**Fix:** Define and enforce one canonical section-label class. The `integrations.module.css` `.sectionLabel` rule is correct — extract it to a shared utility or document it as the standard:
```css
/* shared pattern — apply to every module */
.sectionLabel {
  font-size: var(--text-xs);
  font-weight: var(--fw-semibold);
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}
```
Apply to: billing `.plansGrid` header, connections "Desteklenen Platformlar" / "Bağlı Hesaplar", tracking `HEDEFLER (DESTINATIONS)`, consent all section labels, feeds section labels, workspaces section labels.

**Effort:** S

---

### Item 3 — Empty-state icon inconsistency: three different icons for the same "no data" concept (S)

**Screens affected:** briefing, goals, automation, reports, planning (Kayıtlı Planlar), assistant.

**Issue:** Five screens that share the identical "nothing here yet" state each render a different icon:
- `briefing.png`: briefcase-plus icon
- `goals.png`: briefcase-plus icon (same as briefing — correct match)
- `automation.png`: a different icon (appears to be a calendar/rules icon)
- `reports.png`: a page/document icon
- `assistant.png`: briefcase-plus again

This is inconsistent. The `EmptyState` component exists (`src/components/EmptyState.tsx`) but is not used uniformly. Some screens render their own inline empty divs with different icons, bypassing the shared component entirely.

**Fix:** Audit which screens render their own empty state markup rather than `<EmptyState>`. Replace all inline empty-state divs with `<EmptyState icon="..." title="..." description="..." cta={...} />`. Use a single icon variant (the briefcase-plus is fine, or standardise on a neutral chart/grid icon). The assistant screen's empty state is contextually appropriate (no chats yet), so it may keep the briefcase-plus but should use the `EmptyState` component wrapper for consistent sizing and spacing.

**Effort:** S

---

### Item 4 — `color-mix()` usage in `notifications.module.css` breaks Safari 15 (S)

**Screens affected:** notifications.

**Issue:** `notifications.module.css` uses `color-mix(in srgb, var(--color-primary) 12%, transparent)` for `.badge_info` and `color-mix(in srgb, var(--color-text-muted) 18%, transparent)` for `.filterCount`. Safari 15 and most Android WebViews before Chrome 111 do not support `color-mix()`. Since AYAZ has a PWA mode, this is a real regression risk on iOS Safari.

**Fix:** Replace the two `color-mix()` calls with the equivalent `rgba` values that are already defined as semantic tokens:
- `.badge_info` background: replace with `var(--color-info-bg)` (already `rgba(59, 91, 219, 0.08)`)
- `.filterCount` background: replace with `rgba(107, 114, 128, 0.18)` (inline; no token equivalent — add `--color-muted-bg: rgba(107, 114, 128, 0.12)` to `:root` or use `var(--color-surface-2)` as a safe approximation)

**Effort:** S

---

## Wave 2 — Per-Screen Polish

### Item 5 — `billing.png`: Usage shield ("fatura kalkanı") is buried and the danger state reads as generic (M)

**Screen:** billing.

**Issue:** The resource-usage bar ("KAYNAK KULLANIMI") is the most operationally important element on the billing screen — it tells a Free-plan user they are at 500% of their limit (the screenshot shows a fully red bar: "5 kaynak kullanımda · plan limiti 1"). Despite this critical state, the UI treats it identically to a normal progress bar: same small 8px height, same muted label, no icon, no contextual message, no upgrade prompt adjacent to the danger. The user must read the small grey caption "5 kaynak kullanımda · plan limiti 1" to understand the situation, then scroll down to find the plan comparison. There is no visual connection between the red bar and the "Yükselt" CTA below.

**Fix — Usage Shield Panel:** Replace the current `usageBox` / `usageBarTrack` layout with a dedicated shield panel when usage is at or above the plan limit. The panel sits inline in the "MEVCUT PLAN" card and uses the existing `--color-critical`, `--color-critical-bg`, `--color-critical-text` tokens:

```
┌─────────────────────────────────────────────────────────┐
│  [!] Plan Limitini Aştınız                              │
│  5 bağlı kaynak / limit: 1                              │
│  ████████████████████████████ 500%                      │
│  Yeni verileri senkronize etmek için planınızı yükseltin│
│  [ Hemen Yükselt → Growth ]                             │
└─────────────────────────────────────────────────────────┘
```

Implementation notes:
- Wrap in a `<div>` with `background: var(--color-critical-bg)`, `border: 1.5px solid var(--color-critical)`, `border-radius: var(--radius)`, `padding: var(--space-4)`.
- Show this panel only when `usage >= limit`. Below 80% show the existing quiet bar. Between 80-99% show the bar with `--color-warning` fill and a smaller amber note. At 100%+ show the shield panel with the critical CTA.
- The "Hemen Yükselt" button inside the panel should deep-link to the Growth plan card below (smooth scroll to `#growth-plan` or directly trigger the upgrade modal).
- No new dependencies; uses `--color-critical-*` tokens already in `globals.css`.

**Effort:** M

---

### Item 6 — `seo.png`: Active tab indicator uses `--color-accent` (amber), all other tab strips use `--color-primary` (blue) (S)

**Screen:** seo.

**Issue:** In `seo.module.css`, `.tabBtnActive` uses `border-bottom-color: var(--color-accent)` (the amber `#f59e0b`). Every other tab strip in the app — insights filters, notifications filter bar, integrations category tabs, ads tab strip — uses `var(--color-primary)` (blue) as the active underline. The SEO tab strip is the only exception. Visually it looks intentional but it is not: there is no semantic reason for SEO to use amber.

Additionally, `seo.module.css` uses `--color-accent` for the site-audit button (`.auditBtn`, `.dfsBtn`), the focus ring on the period selector, and the active state on `.strategyBtnActive`. These are all amber buttons on a screen that is otherwise blue-primary. The result is an accent-colour intrusion that makes the SEO module feel like a different product.

**Fix:** In `seo.module.css`:
1. Change `.tabBtnActive { border-bottom-color: var(--color-accent) }` to `var(--color-primary)`.
2. Change `.auditBtn` and `.dfsBtn` `background: var(--color-accent)` to `var(--color-primary)` / `var(--color-primary-hover)`.
3. Change the `outline` on `.periodSelect:focus` and `.auditInput:focus` from `var(--color-accent)` to `var(--color-primary)` (matching every other input in the system).
4. Change `.strategyBtnActive { border-color: var(--color-accent) }` to `var(--color-primary)`.

Reserve `--color-accent` (amber) for warning/caution states only, consistent with how it is defined in the design token spec.

**Effort:** S

---

### Item 7 — `integrations.png`: Progress hero does not surface a "connected: 0" zero-state experience well; wizard lacks a "skip" affordance (S)

**Screen:** integrations.

**Issue:** With 0/8 integrations connected (as in the screenshot), the progress bar is at 0% and the tagline is a link ("İlk entegrasyonunuzu bağlayın ve verilerinizi görün"). This is fine. However the wizard panel ("Hızlı Kurulum Sihirbazı") shows all three steps at full opacity with equal visual weight — there is no visual indication that step 1 is the "active" step. Steps 2 and 3 should be visually muted to communicate linear progression. Additionally, there is no explicit "skip" or "dismiss later" affordance for users who want to browse the catalog first. The wizard panel in this state occupies 40% of the viewport, pushing the catalog grid below the fold.

**Fix:**
1. Apply `opacity: 0.45` and `pointer-events: none` to wizard steps 2 and 3 when step 1 is not yet complete. Add a subtle vertical connector line between step numbers (a 1px `--color-border` line) to reinforce sequence.
2. The existing "Kapat" button is the dismiss affordance — make it more prominent. Change it from plain text to a `btnSecondary`-styled link with a border, so it reads as an intentional action rather than a close handle.
3. Reduce the wizard panel height by collapsing the body padding from `var(--space-5)` to `var(--space-4)` between steps when there are no quick-connect buttons yet to show.

**Effort:** S

---

### Item 8 — `audit.png` (Hesap Sağlık Taraması): "VERİ KALİTESİ" section is buried at the bottom and the data-quality finding is invisible (M)

**Screen:** audit.

**Issue:** The "VERİ KALİTESİ" section appears at the very bottom of the audit screen, after Reklam Performansı, Ölçümleme, Bütçe, İçerik, Hedefler, İçgörüler. The "Veri kalitesi sağlıklı" finding is displayed as a passed item (green checkmark) with no quantitative detail. This hides the data-trust feature ("veri-güven") entirely. A user with a double-count issue or an attribution gap would never find this section because it is always at the bottom and always shows green even when the underlying data quality has sub-issues.

The `insights.png` screen (İçgörüler ve Uyarılar) does surface data-quality badges ("KRITIK", "UYARI") on insight cards, but there is no persistent data-quality badge visible on the navigation or on the Komuta Merkezi.

**Fix:**
1. **Re-order audit sections:** Move "VERİ KALİTESİ" to position 2, immediately after "REKLAM PERFORMANSI". It is the most systemic category because a broken pixel contaminates all other scores.
2. **Add a data-quality badge to the section header:** When all checks pass, show a `--color-success-text` "Sağlıklı" badge beside the section label. When any sub-check fails, show `--color-critical-text` "Sorun Var" with a count. This uses the existing badge pattern from the audit section headers (e.g. "1 sorun · 0 uyarı · 0 geçti").
3. **Surface on Komuta Merkezi:** Add a "Veri Kalitesi" row to the "MODÜL DURUMU" grid on `command-center.png`. Currently the grid has 8 cells; it can take a 9th or replace "KVKK UYUM" (which already shows 100/100 and is low urgency). Show: data quality score, last check timestamp, and a link.

**Effort:** M

---

### Item 9 — `notifications.png`: No usage-limit / plan-shield alert type; critical notifications lack an explicit "Go Fix" CTA (S)

**Screen:** notifications.

**Issue:** The notification list correctly shows severity stripes (red for KRİTİK, amber for UYARI, blue for BİLGİ) and severity badges. However:
1. There is no notification type for "plan limit reached" or "integration sync paused due to limit". The billing shield event from Item 5 never surfaces here.
2. KRİTİK notifications show "Devamını oku" (read more) as their only action. A user who clicks this reads the full text but then has to manually navigate to İçgörüler. There is no inline "Git →" button pointing to the specific screen, unlike the Komuta Merkezi which shows "İçgörüler →" links.

**Fix:**
1. Add a "LİMİT" severity type to the badge and stripe system. In `notifications.module.css`: add `.stripePlan { background: var(--color-purple); }` and `.badge_plan { background: var(--color-ai-bg); color: var(--color-ai-text); }`. Wire it to the billing shield event.
2. For KRİTİK and UYARI notifications that have a linked destination (insights, audit, ads), render an inline "Git →" ghost button at the bottom-right of the row, next to the timestamp. It uses the existing `btnSecondary` pattern from integrations. The destination URL is already embedded in the insight payload — pass it through.

**Effort:** S

---

### Item 10 — `tracking.png` (Ölçümleme): Overly dense; consent variable section is too large relative to content (M)

**Screen:** tracking.

**Issue:** The Ölçümleme screen is the most visually dense in the app. The left panel ("İzleme Kaynakları") is a narrow sidebar at ~220px with a single item (EasyCep Web), while the right panel contains: a page title, two status badges ("100 Toplam Olay", "10 Hata"), three tabs (Kurulum / Olay Kalitesi / Olay Günlüğü), a code snippet block (COLLECT URL + copy button), a "Entegrasyon Snippet'ini Göster" disclosure, a "Çerez Rıza Değişkeni" card with an input, and then the HEDEFLER section with two destination blocks — each containing a platform badge, a pixel ID, a "Rıza yok" / "KVKK rıza" badge, a "Sil" button, a consent mode selector (radio + checkboxes in a 2-column grid), and a "Kaydet" button. The GA4 destination is a near-copy of the Meta one, doubling the visual noise.

The two destination cards take up roughly 60% of the visible area for what is essentially a two-line configuration per platform.

**Fix:**
1. **Collapse destinations into a table row by default.** Each destination shows: platform badge, measurement ID, consent status badge, Sil button. Expand inline to reveal the consent checkbox grid. This matches the `feeds.png` pattern (Google Shopping / Meta Katalog as compact rows with a chevron toggle).
2. **Move "10 Hata" badge** to use `--color-critical-bg` / `--color-critical-text` instead of the current red badge style (which appears to be an ad-hoc inline style not from the token set).
3. **Two-column destination grid** for when there are 2+ destinations — remove the stacked single-column layout and place them side-by-side at ≥ 900px viewport.

**Effort:** M

---

### Item 11 — `consent.png` (KVKK Rıza Merkezi): Section padding is inconsistent; "RIZA DENETİM İZİ" table is unstyled (S)

**Screen:** consent.

**Issue:** The consent screen is one of the tallest pages (the screenshot is 2506px vs the 1440px average). The "RIZA DENETİM İZİ" table at the bottom appears as a plain HTML table with no alternating row color, no column header styling matching the token system, and no `border-radius` on the container. Compare to the SEO "TOP SORGULAR" table, which uses `var(--text-xs)` uppercase headers, `var(--color-surface-2)` hover rows, and a `--color-border` bottom separator.

Additionally, the "KVKK UYUM KONTROL LİSTESİ" section label sits outside any card and has no card wrapper, making it visually float.

**Fix:**
1. Wrap "KVKK UYUM KONTROL LİSTESİ" in a `<SectionCard>` with title prop "KVKK Uyum Kontrol Listesi". The current layout puts it bare on the page.
2. Apply the `seo.module.css` table style (or an identical set of tokens) to the "RIZA DENETİM İZİ" table: `--text-xs` uppercase headers, `border-bottom: 1px solid var(--color-border)` on rows, `--color-surface-2` hover, `border-radius: var(--radius)` on the wrapping card.
3. The "RIZA ORANI" and "KVKK UYUM SKORU" stat boxes would benefit from being inside a 2-column `KpiCard` grid rather than a bespoke flex layout — they already contain exactly the data (number + label + progress bar) that `KpiCard` is designed for.

**Effort:** S

---

### Item 12 — `budget-simulator.png`: Channel bar chart uses non-token purple/green/amber tones that do not match `--chart-*` tokens (S)

**Screen:** budget-simulator.

**Issue:** The "BAZ SENARYO KARŞILAŞTIRMASI" bar chart shows Meta Ads in a pastel purple, Google Ads in a pastel green, Tiktok Ads in a pastel orange — these are lighter tints of the chart colors, not the `--chart-*` tokens themselves. The "Baz Dönüşüm" bars use near-white fills (very low contrast), while "Senaryo Dönüşüm" bars use the full saturated colors. The legend confirms the issue: the "Baz Dönüşüm" fill is almost invisible against the white background.

Compare to `creatives.png` and `executive.png` where Meta = `--chart-4` (purple `#7c3aed`), Google = `--chart-google` (green `#10b981`), TikTok = `--chart-tiktok` (amber `#f59e0b`). The budget simulator uses tinted versions instead.

**Fix:** In the Recharts `BarChart` component for the simulator, pass the colors from `src/lib/chartColors.ts`:
- "Baz" series: use the channel color at 35% opacity (`rgba(124, 58, 237, 0.35)` for Meta, etc.) so it reads as a lighter variant of the same hue rather than an unrelated grey-white.
- "Senaryo" series: use full `--chart-*` token values (already in `chartColors.ts`).
- This creates a clear visual relationship: scenario vs. baseline for the same channel uses the same hue family.

**Effort:** S

---

### Item 13 — `reports.png` and `automation.png` / `goals.png` / `planning.png`: Content-light screens waste large amounts of whitespace (S)

**Screens:** reports, automation, goals, planning (Bütçe Planlayıcı with error), briefing.

**Issue:** Five screens show a single item or empty state in a card, leaving 60–70% of the page height as empty `--color-bg` grey. This reads as "broken" or "still loading" rather than "empty, here's what to do." The screens are:
- **reports:** one report card, then 500px of grey
- **automation:** empty state card, then 600px of grey
- **goals:** empty state card, then 600px of grey
- **planning:** error text in a card, then 600px of grey
- **briefing:** two cards, then 600px of grey

**Fix:** For each of these screens, add a "Getting Started" strip below the main empty/single-item card. This is a 3-column horizontal feature teaser (already implemented as `<GettingStarted>` on the dashboard screen) showing related features the user could activate. For example:
- **reports:** "Rapor Oluşturucu ile sorgu yaz →", "CSV ile dışa aktar →", "Otomatik rapor planla →"
- **automation:** "Örnek kural: ROAS < 2x olunca uyar", "Bütçe aşımı alertı", "Dönüşüm düşüşü tespit"
- **goals:** "Örnek hedef: Aylık ₺500K gelir", "ROAS hedefi koy", "Dönüşüm hedefi izle"

This reuses the `GettingStarted` component and requires only a props change, no new component.

**Effort:** S

---

## Wave 3 — Surfacing Under-Built Features

### Item 14 — Data-quality / double-count "veri-güven" badge: missing from dashboard KPI cards (M)

**Screens:** dashboard (Panel), executive (Yönetici), command-center.

**Issue:** The backend's data-quality layer (seen working in `audit.png` as "Veri Kalitesi: Yinelenen hesap veya KPI tutarsızlığı tespit edilmedi") is not surfaced on the primary KPI cards. On `dashboard.png`, the five KPI cards (Harcama, Gösterim, Tıklama, Dönüşüm, ROAS) display numbers with no indication of data confidence. On `executive.png` and `command-center.png`, the four top-level KPIs (Toplam Harcama, Toplam Gelir, ROAS, Dönüşüm) have the same gap. If the system detects a double-count or stale sync, the user currently has no way to know the numbers are unreliable without navigating to the Audit screen.

**Fix — Data-trust badge on KPI cards:** Add an optional `dataQuality` prop to `KpiCard`:

```
KpiCard props addition:
  dataQuality?: 'ok' | 'warn' | 'stale'
```

Render as a small icon below the KPI value:
- `ok` → no badge (default, silent)
- `warn` → amber dot + tooltip "Veri tutarsızlığı tespit edildi. Denetim raporunu görüntüle."
- `stale` → grey clock icon + "Son senkronizasyon 6+ saat önce"

This surfaces the veri-güven signal at the exact moment the user is reading the number, without adding permanent visual noise (the `ok` state is invisible).

**Effort:** M

---

### Item 15 — `billing.png`: Plan comparison grid is the entire page; there is no invoice history, next payment date, or cancellation-date context (M)

**Screen:** billing.

**Issue:** The billing screen contains only two sections: "MEVCUT PLAN" (with the usage bar) and "PLAN KARŞILAŞTIRMA" (the 4-column plan grid). There is no:
- Next billing date / renewal date
- Invoice history (even a stub)
- What happens when the plan is cancelled (data retention policy)
- Cancellation confirmation flow (the "Aboneliği İptal Et" button exists in the CSS via `.cancelBtn` but is not visible in the screenshot — it may be hidden for the Free plan or simply not rendered)

For a SaaS billing screen this is a significant trust gap, especially since Turkish consumers expect transparency around subscription terms (KVKK / consumer protection context).

**Fix:** Add a third section "FATURA BİLGİLERİ" below the current plan card, before the plan comparison grid:

```
FATURA BİLGİLERİ
┌────────────────────────────────────────────────────┐
│  Sonraki Fatura:  — (Ücretsiz plan)                │
│  Son Ödeme:       —                                │
│  Fatura Geçmişi:  Henüz fatura yok                 │
└────────────────────────────────────────────────────┘
```

For paid plans this shows the real renewal date and a list of past invoices (date, amount, status, PDF download button). For the Free plan it shows "Ücretli plana geçtiğinizde faturalar burada görünür." Use a `SectionCard` with `title="Fatura Bilgileri"`. This requires a `/api/billing/invoices` endpoint — if not yet available, render the section with a skeleton placeholder so the layout is reserved.

**Effort:** M

---

## Summary Table

| # | Screen(s) | Issue | Fix Type | Effort |
|---|-----------|-------|----------|--------|
| 1 | 18 screens | Raw rem units not migrated to `--space-*` / `--text-*` tokens | Token substitution | S |
| 2 | 12 screens | Section-label styling inconsistent (3 different styles) | CSS standardisation | S |
| 3 | 6 screens | EmptyState component bypassed, inconsistent icons | Component adoption | S |
| 4 | notifications | `color-mix()` breaks Safari 15 | Token fallback | S |
| 5 | billing | Usage-shield buried; no critical CTA adjacent to red bar | New panel variant | M |
| 6 | seo | `--color-accent` used for primary actions — wrong token | Token correction | S |
| 7 | integrations | Wizard steps not sequentially muted; dismiss under-styled | Interaction polish | S |
| 8 | audit | VERİ KALİTESİ section buried; data-quality not on Komuta | Reorder + surface | M |
| 9 | notifications | No plan-limit alert type; KRİTİK missing inline CTA | New badge + button | S |
| 10 | tracking | Destination cards too tall; table dense; stacked layout | Collapse pattern | M |
| 11 | consent | Audit table unstyled; section label outside card | Token table style | S |
| 12 | budget-simulator | Bar chart tints don't match `--chart-*` tokens | chartColors.ts fix | S |
| 13 | reports, automation, goals, planning, briefing | Content-light screens: 60–70% empty grey | GettingStarted strip | S |
| 14 | dashboard, executive, command-center | No data-trust badge on KPI cards | KpiCard prop | M |
| 15 | billing | No invoice history / renewal date / cancellation context | New billing section | M |

**Wave 1 (global):** Items 1–4 — touch many files but are mechanical. Ship together.
**Wave 2 (per-screen):** Items 5–13 — ship in two sprints, prioritise 5, 6, 8, 9 first.
**Wave 3 (feature surface):** Items 14–15 — require backend coordination for real data; can ship with stubs first.

---

*Audit produced by UX/UI Designer role, AYAZ platform. Sonnet 4.6. 2026-06-30.*
