'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  previewBudget,
  createBudgetPlan,
  getBudgetPlans,
  deleteBudgetPlan,
  OBJECTIVE_LABELS,
  STATUS_LABELS,
  type AllocationResult,
  type BudgetPlan,
  type BudgetObjective,
  type BudgetStatus,
  type PlatformAllocation,
} from '@/lib/budget-api';
import AppNav from '@/components/AppNav';
import styles from './planning.module.css';

// --- Currency formatter ---

const TRY = new Intl.NumberFormat('tr-TR', {
  style: 'currency',
  currency: 'TRY',
  maximumFractionDigits: 0,
});

function fmtTRY(val: number): string {
  return TRY.format(val);
}

function fmtNum(val: number, decimals = 2): string {
  return val.toLocaleString('tr-TR', { maximumFractionDigits: decimals });
}

// Next month YYYY-MM for default
function nextMonth(): string {
  const d = new Date();
  d.setMonth(d.getMonth() + 1);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

// --- Delta badge ---

function DeltaBadge({ pct }: { pct: number }) {
  if (pct > 0.5) {
    return (
      <span className={`${styles.deltaBadge} ${styles.deltaUp}`}>
        ▲ {fmtNum(pct, 1)}%
      </span>
    );
  }
  if (pct < -0.5) {
    return (
      <span className={`${styles.deltaBadge} ${styles.deltaDown}`}>
        ▼ {fmtNum(Math.abs(pct), 1)}%
      </span>
    );
  }
  return (
    <span className={`${styles.deltaBadge} ${styles.deltaFlat}`}>
      — 0%
    </span>
  );
}

// --- Status badge ---

function StatusBadge({ status }: { status: BudgetStatus }) {
  const cls: Record<BudgetStatus, string> = {
    draft: styles.statusDraft,
    active: styles.statusActive,
    archived: styles.statusArchived,
  };
  return (
    <span className={`${styles.statusBadge} ${cls[status] ?? ''}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

// --- Campaign breakdown (expandable) ---

function CampaignBreakdown({ platform }: { platform: PlatformAllocation }) {
  if (!platform.campaigns || platform.campaigns.length === 0) return null;

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className={styles.campaignTable}>
        <thead>
          <tr>
            <th>Kampanya</th>
            <th style={{ textAlign: 'right' }}>Önerilen Bütçe</th>
            <th style={{ textAlign: 'right' }}>Pay</th>
            <th style={{ textAlign: 'right' }}>ROAS</th>
            <th style={{ textAlign: 'right' }}>Beklenen Dönüşüm</th>
            <th style={{ textAlign: 'right' }}>Beklenen Gelir</th>
          </tr>
        </thead>
        <tbody>
          {platform.campaigns.map((c) => (
            <tr key={c.campaign_id}>
              <td style={{ fontWeight: 500 }}>{c.name}</td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {fmtTRY(c.recommended_budget)}
              </td>
              <td style={{ textAlign: 'right', color: 'var(--color-text-muted)' }}>
                %{fmtNum(c.recommended_share, 1)}
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {fmtNum(c.roas, 2)}x
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {fmtNum(c.expected_conversions, 0)}
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {fmtTRY(c.expected_revenue)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Platform row ---

function PlatformRow({ platform }: { platform: PlatformAllocation }) {
  const [expanded, setExpanded] = useState(false);
  const hasCampaigns = platform.campaigns && platform.campaigns.length > 0;

  return (
    <div className={styles.platformRow}>
      <div
        className={styles.platformHeader}
        onClick={() => hasCampaigns && setExpanded((v) => !v)}
        role={hasCampaigns ? 'button' : undefined}
        tabIndex={hasCampaigns ? 0 : undefined}
        onKeyDown={(e) => hasCampaigns && e.key === 'Enter' && setExpanded((v) => !v)}
        aria-expanded={hasCampaigns ? expanded : undefined}
      >
        <span className={styles.platformLabel}>{platform.label}</span>

        <div className={styles.platformStats}>
          <div className={styles.platformStat}>
            <span className={styles.platformStatValue}>{fmtTRY(platform.recommended_budget)}</span>
            <span className={styles.platformStatLabel}>Önerilen Bütçe</span>
          </div>
          <div className={styles.platformStat}>
            <span className={styles.platformStatValue}>
              %{fmtNum(platform.recommended_share, 1)}
            </span>
            <span className={styles.platformStatLabel}>Pay</span>
          </div>
          <div className={styles.platformStat}>
            <span className={styles.platformStatValue}>{fmtNum(platform.expected_roas, 2)}x</span>
            <span className={styles.platformStatLabel}>Beklenen ROAS</span>
          </div>
          <div className={styles.platformStat}>
            <span className={styles.platformStatValue}>{fmtNum(platform.expected_conversions, 0)}</span>
            <span className={styles.platformStatLabel}>Beklenen Dönüşüm</span>
          </div>
          <div className={styles.platformStat}>
            <span className={styles.platformStatValue}>{fmtTRY(platform.expected_revenue)}</span>
            <span className={styles.platformStatLabel}>Beklenen Gelir</span>
          </div>
          <DeltaBadge pct={platform.delta_pct} />
        </div>

        {hasCampaigns && (
          <span
            className={`${styles.expandChevron} ${expanded ? styles.expandChevronOpen : ''}`}
            aria-hidden="true"
          >
            &#9654;
          </span>
        )}
      </div>

      <div className={styles.shareBarTrack}>
        <div
          className={styles.shareBarFill}
          style={{ width: `${Math.min(platform.recommended_share, 100)}%` }}
          title={`%${fmtNum(platform.recommended_share, 1)} pay`}
        />
      </div>

      {expanded && hasCampaigns && <CampaignBreakdown platform={platform} />}
    </div>
  );
}

// --- Allocation view ---

function AllocationView({ result }: { result: AllocationResult }) {
  return (
    <>
      {/* Plan-level projection cards */}
      <div className={styles.projectionCards}>
        <div className={styles.projCard}>
          <div className={styles.projValue}>
            {fmtNum(result.projection.expected_conversions, 0)}
          </div>
          <div className={styles.projLabel}>Beklenen Dönüşüm</div>
        </div>
        <div className={styles.projCard}>
          <div className={styles.projValue}>
            {fmtTRY(result.projection.expected_revenue)}
          </div>
          <div className={styles.projLabel}>Beklenen Gelir</div>
        </div>
        <div className={styles.projCard}>
          <div className={styles.projValue}>
            {fmtNum(result.projection.expected_roas, 2)}x
          </div>
          <div className={styles.projLabel}>Beklenen ROAS</div>
        </div>
      </div>

      {/* Platform rows */}
      {result.platforms.length === 0 ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>
            Geçmiş harcama verisi bulunamadı — bütçe dağılımı hesaplanamıyor.
          </span>
        </div>
      ) : (
        <div className={styles.platformList}>
          {result.platforms.map((p) => (
            <PlatformRow key={p.channel} platform={p} />
          ))}
        </div>
      )}

      {/* Notes */}
      {result.notes && result.notes.length > 0 && (
        <div className={styles.notesBlock}>
          <span className={styles.sectionTitleInline} style={{ marginBottom: '0.35rem' }}>
            Nasıl Hesaplandı
          </span>
          {result.notes.map((note, i) => (
            <p key={i} className={styles.noteLine}>
              {note}
            </p>
          ))}
        </div>
      )}
    </>
  );
}

// --- Saved plans list ---

function SavedPlansList({
  plans,
  loading,
  error,
  deletingId,
  onDelete,
  onLoad,
}: {
  plans: BudgetPlan[];
  loading: boolean;
  error: string | null;
  deletingId: string | null;
  onDelete: (id: string) => void;
  onLoad: (plan: BudgetPlan) => void;
}) {
  if (loading) {
    return (
      <div className={styles.stateBoxSm}>
        <span className={styles.muted}>Planlar yükleniyor...</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className={styles.stateBoxSm}>
        <span className={styles.errorText}>{error}</span>
      </div>
    );
  }
  if (plans.length === 0) {
    return (
      <div className={styles.stateBoxSm}>
        <span className={styles.muted}>Henüz kayıtlı plan yok.</span>
      </div>
    );
  }

  return (
    <div className={styles.tableWrap}>
      <table className={styles.plansTable}>
        <thead>
          <tr>
            <th>Plan Adı</th>
            <th>Ay</th>
            <th style={{ textAlign: 'right' }}>Toplam Bütçe</th>
            <th>Hedef</th>
            <th>Durum</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {plans.map((plan) => (
            <tr
              key={plan.id}
              onClick={() => onLoad(plan)}
              title="Planı yükle"
            >
              <td style={{ fontWeight: 600 }}>{plan.name}</td>
              <td style={{ color: 'var(--color-text-muted)' }}>{plan.period_month}</td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {fmtTRY(plan.total_budget)}
              </td>
              <td style={{ color: 'var(--color-text-muted)', fontSize: '0.8125rem' }}>
                {OBJECTIVE_LABELS[plan.objective] ?? plan.objective}
              </td>
              <td>
                <StatusBadge status={plan.status} />
              </td>
              <td
                onClick={(e) => e.stopPropagation()}
                style={{ whiteSpace: 'nowrap' }}
              >
                <button
                  className={styles.dangerBtn}
                  disabled={deletingId === plan.id}
                  onClick={() => onDelete(plan.id)}
                  aria-label={`${plan.name} planını sil`}
                >
                  {deletingId === plan.id ? '...' : 'Sil'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Main page ---

export default function PlanningPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  // ---- Planner form state ----
  const [planName, setPlanName] = useState('');
  const [periodMonth, setPeriodMonth] = useState(nextMonth);
  const [totalBudget, setTotalBudget] = useState('');
  const [objective, setObjective] = useState<BudgetObjective>('balanced');
  const [lookbackDays, setLookbackDays] = useState<30 | 60 | 90>(30);

  // ---- Preview state ----
  const [allocation, setAllocation] = useState<AllocationResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // ---- Save state ----
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // ---- Saved plans ----
  const [plans, setPlans] = useState<BudgetPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(true);
  const [plansError, setPlansError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  // ---- Debounce ref ----
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- Load plans on mount ----
  const fetchPlans = useCallback(async () => {
    setPlansLoading(true);
    setPlansError(null);
    try {
      const data = await getBudgetPlans();
      setPlans(data);
    } catch (err: unknown) {
      setPlansError(err instanceof Error ? err.message : 'Planlar yüklenemedi');
    } finally {
      setPlansLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchPlans();
  }, [fetchPlans]);

  // ---- Debounced preview ----
  useEffect(() => {
    const budget = parseFloat(totalBudget);
    if (!totalBudget || isNaN(budget) || budget <= 0) {
      setAllocation(null);
      setPreviewError(null);
      return;
    }

    if (debounceTimer.current) clearTimeout(debounceTimer.current);

    debounceTimer.current = setTimeout(async () => {
      setPreviewLoading(true);
      setPreviewError(null);
      try {
        const result = await previewBudget({
          total_budget: budget,
          objective,
          lookback_days: lookbackDays,
          currency: 'TRY',
        });
        setAllocation(result);
      } catch (err: unknown) {
        setPreviewError(err instanceof Error ? err.message : 'Önizleme yüklenemedi');
        setAllocation(null);
      } finally {
        setPreviewLoading(false);
      }
    }, 400);

    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [totalBudget, objective, lookbackDays]);

  // ---- Save plan ----
  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    const budget = parseFloat(totalBudget);
    if (!budget || isNaN(budget) || budget <= 0) return;

    setSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const created = await createBudgetPlan({
        name: planName.trim() || `Plan ${periodMonth}`,
        period_month: periodMonth,
        total_budget: budget,
        objective,
        lookback_days: lookbackDays,
        currency: 'TRY',
      });
      setPlans((prev) => [created, ...prev]);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 4000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Plan kaydedilemedi');
    } finally {
      setSaving(false);
    }
  }

  // ---- Delete plan ----
  async function handleDelete(id: string) {
    setDeletingId(id);
    try {
      await deleteBudgetPlan(id);
      setPlans((prev) => prev.filter((p) => p.id !== id));
    } catch {
      // non-fatal
    } finally {
      setDeletingId(null);
    }
  }

  // ---- Load plan into form ----
  function handleLoadPlan(plan: BudgetPlan) {
    setPlanName(plan.name);
    setPeriodMonth(plan.period_month);
    setTotalBudget(String(plan.total_budget));
    setObjective(plan.objective);
    setLookbackDays((plan.lookback_days as 30 | 60 | 90) || 30);
    if (plan.allocations) {
      setAllocation(plan.allocations);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  const budgetNum = parseFloat(totalBudget);
  const canSave = !isNaN(budgetNum) && budgetNum > 0;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Bütçe Planlayıcı</h1>
          <p className={styles.pageSubtitle}>
            Gelecek ayın toplam bütçesini girin; sistem geçmiş performansa göre
            platform ve kampanya bazında dağıtsın.
          </p>
        </div>

        {/* Planner form + preview */}
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <span className={styles.cardTitle}>Yeni Plan Oluştur</span>
          </div>

          <form onSubmit={handleSave}>
            <div className={styles.cardBody}>
              <div className={styles.formGrid}>
                {/* Plan adı */}
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="plan-name">
                    Plan Adı
                  </label>
                  <input
                    id="plan-name"
                    className={styles.input}
                    placeholder={`Plan ${periodMonth}`}
                    value={planName}
                    onChange={(e) => setPlanName(e.target.value)}
                    disabled={saving}
                  />
                </div>

                {/* Ay */}
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="period-month">
                    Ay
                  </label>
                  <input
                    id="period-month"
                    className={styles.input}
                    type="month"
                    value={periodMonth}
                    onChange={(e) => setPeriodMonth(e.target.value)}
                    disabled={saving}
                  />
                </div>

                {/* Toplam bütçe */}
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="total-budget">
                    Toplam Bütçe
                  </label>
                  <div className={styles.inputWithPrefix}>
                    <span className={styles.inputPrefix}>₺</span>
                    <input
                      id="total-budget"
                      className={styles.input}
                      type="number"
                      min="1"
                      step="1"
                      placeholder="örn. 50000"
                      value={totalBudget}
                      onChange={(e) => setTotalBudget(e.target.value)}
                      disabled={saving}
                      aria-label="Toplam bütçe (TRY)"
                    />
                  </div>
                </div>

                {/* Hedef */}
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="objective">
                    Hedef
                  </label>
                  <select
                    id="objective"
                    className={styles.select}
                    value={objective}
                    onChange={(e) => setObjective(e.target.value as BudgetObjective)}
                    disabled={saving}
                  >
                    {(Object.entries(OBJECTIVE_LABELS) as [BudgetObjective, string][]).map(
                      ([v, l]) => (
                        <option key={v} value={v}>
                          {l}
                        </option>
                      ),
                    )}
                  </select>
                </div>

                {/* Geçmiş veri */}
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="lookback-days">
                    Geçmiş Veri
                  </label>
                  <select
                    id="lookback-days"
                    className={styles.select}
                    value={lookbackDays}
                    onChange={(e) =>
                      setLookbackDays(Number(e.target.value) as 30 | 60 | 90)
                    }
                    disabled={saving}
                  >
                    <option value={30}>Son 30 gün</option>
                    <option value={60}>Son 60 gün</option>
                    <option value={90}>Son 90 gün</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Preview area */}
            {!totalBudget || isNaN(budgetNum) || budgetNum <= 0 ? (
              <div className={styles.stateBoxSm}>
                <span className={styles.muted}>
                  Önizleme için toplam bütçe girin.
                </span>
              </div>
            ) : previewLoading ? (
              <div className={styles.previewLoading}>
                <div className={styles.spinner} aria-hidden="true" />
                Yükleniyor...
              </div>
            ) : previewError ? (
              <div className={styles.stateBoxSm}>
                <span className={styles.errorText}>{previewError}</span>
              </div>
            ) : allocation ? (
              <AllocationView result={allocation} />
            ) : null}

            {/* Save row */}
            <div className={styles.saveRow}>
              <button
                type="submit"
                className={styles.primaryBtn}
                disabled={saving || !canSave}
              >
                {saving ? 'Kaydediliyor...' : 'Planı Kaydet'}
              </button>
              {saveError && (
                <span className={styles.formError} role="alert">
                  {saveError}
                </span>
              )}
              {saveSuccess && (
                <span className={styles.formSuccess} role="status">
                  Plan başarıyla kaydedildi.
                </span>
              )}
            </div>
          </form>
        </div>

        {/* Saved plans */}
        <div className={styles.card}>
          <div className={styles.cardHeader}>
            <span className={styles.cardTitle}>Kayıtlı Planlar</span>
          </div>

          <SavedPlansList
            plans={plans}
            loading={plansLoading}
            error={plansError}
            deletingId={deletingId}
            onDelete={handleDelete}
            onLoad={handleLoadPlan}
          />
        </div>
      </main>
    </div>
  );
}
