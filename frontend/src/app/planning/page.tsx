'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import { parseApiError } from '@/lib/parseApiError';
import {
  previewBudget,
  createBudgetPlan,
  getBudgetPlans,
  deleteBudgetPlan,
  getPlanActuals,
  OBJECTIVE_LABELS,
  STATUS_LABELS,
  type AllocationResult,
  type BudgetPlan,
  type BudgetObjective,
  type BudgetStatus,
  type PlatformAllocation,
  type PlanActuals,
  type ActualChannel,
} from '@/lib/budget-api';
import AppNav from '@/components/AppNav';
import EmptyState from '@/components/EmptyState';
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

// --- Plan vs Actuals panel ---

function PlanActualsPanel({
  actuals,
}: {
  actuals: PlanActuals;
}) {
  const { totals, channels, notes, days_elapsed } = actuals;

  const TRYfmt = new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: actuals.currency || 'TRY',
    maximumFractionDigits: 0,
  });

  function fmtCurr(val: number) {
    return TRYfmt.format(val);
  }

  const pacePct = Math.min(totals.pace_pct, 100);
  const timePct = Math.min(totals.time_pace_pct, 100);

  const verdict = notes[0] ?? null;

  return (
    <div className={styles.actualsPanel}>
      {/* Pacing summary */}
      <div className={styles.pacingSection}>
        <div className={styles.pacingRow}>
          <span className={styles.pacingLabel}>Harcama</span>
          <span className={styles.pacingValue}>
            {fmtCurr(totals.actual_spend)}
            <span className={styles.pacingOf}> / {fmtCurr(totals.planned_budget)}</span>
            <span className={styles.pacingPct}> (%{fmtNum(totals.pace_pct, 1)})</span>
          </span>
        </div>
        <div className={styles.pacingBarTrack}>
          <div
            className={styles.pacingBarFill}
            style={{ width: `${pacePct}%` }}
            aria-label={`Harcama temposu %${fmtNum(totals.pace_pct, 1)}`}
          />
          {/* time marker */}
          <div
            className={styles.pacingTimeMarker}
            style={{ left: `${timePct}%` }}
            title={`Süre temposu: %${fmtNum(totals.time_pace_pct, 1)}`}
          />
        </div>
        <div className={styles.pacingSubRow}>
          <span className={styles.muted}>
            Süre: %{fmtNum(totals.time_pace_pct, 1)} ({actuals.days_elapsed}/{actuals.days_in_month} gün)
          </span>
        </div>
        {verdict && (
          <p className={styles.actualsVerdict}>{verdict}</p>
        )}
      </div>

      {/* Plan-level KPI cards */}
      <div className={styles.actualsCards}>
        <div className={styles.projCard}>
          <div className={styles.projValue}>{fmtCurr(totals.planned_budget)}</div>
          <div className={styles.projLabel}>Planlanan Bütçe</div>
        </div>
        <div className={styles.projCard}>
          <div className={styles.projValue}>{fmtCurr(totals.actual_spend)}</div>
          <div className={styles.projLabel}>Gerçekleşen Harcama</div>
        </div>
        <div className={styles.projCard}>
          <div className={styles.projValue}>{fmtCurr(totals.actual_revenue)}</div>
          <div className={styles.projLabel}>Gerçekleşen Gelir</div>
        </div>
        <div className={styles.projCard}>
          <div className={styles.projValue}>{fmtNum(totals.actual_roas, 2)}x</div>
          <div className={styles.projLabel}>Gerçekleşen ROAS</div>
        </div>
      </div>

      {/* Per-channel table */}
      {channels.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className={styles.actualsTable}>
            <thead>
              <tr>
                <th>Kanal</th>
                <th style={{ textAlign: 'right' }}>Planlanan</th>
                <th style={{ textAlign: 'right' }}>Gerçekleşen</th>
                <th>Tempo</th>
                <th style={{ textAlign: 'right' }}>ROAS</th>
                <th style={{ textAlign: 'right' }}>Sapma</th>
              </tr>
            </thead>
            <tbody>
              {channels.map((ch: ActualChannel) => (
                <ActualChannelRow key={ch.channel} ch={ch} fmtCurr={fmtCurr} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ActualChannelRow({
  ch,
  fmtCurr,
}: {
  ch: ActualChannel;
  fmtCurr: (v: number) => string;
}) {
  const barPct = Math.min(ch.pace_pct, 100);
  const isAhead = ch.variance_pct > 0.5;
  const isBehind = ch.variance_pct < -0.5;

  return (
    <tr>
      <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{ch.label}</td>
      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {fmtCurr(ch.planned_budget)}
      </td>
      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {fmtCurr(ch.actual_spend)}
      </td>
      <td style={{ minWidth: 100 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <div className={styles.channelBarTrack}>
            <div
              className={styles.channelBarFill}
              style={{ width: `${barPct}%` }}
            />
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
            %{fmtNum(ch.pace_pct, 1)}
          </span>
        </div>
      </td>
      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {fmtNum(ch.actual_roas, 2)}x
      </td>
      <td style={{ textAlign: 'right' }}>
        <span
          className={`${styles.deltaBadge} ${
            isAhead ? styles.deltaUp : isBehind ? styles.deltaDown : styles.deltaFlat
          }`}
        >
          {isAhead ? '▲' : isBehind ? '▼' : '—'}{' '}
          {fmtNum(Math.abs(ch.variance_pct), 1)}%
        </span>
      </td>
    </tr>
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
  onActuals,
  actualsLoadingId,
}: {
  plans: BudgetPlan[];
  loading: boolean;
  error: string | null;
  deletingId: string | null;
  onDelete: (id: string) => void;
  onLoad: (plan: BudgetPlan) => void;
  onActuals: (plan: BudgetPlan) => void;
  actualsLoadingId: string | null;
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
      <EmptyState
        title="Plan verileri yüklenemedi"
        subtitle={error}
      />
    );
  }
  if (plans.length === 0) {
    return (
      <EmptyState
        title="Henüz kayıtlı plan yok"
        subtitle="Bütçe planlayıcısından yeni bir plan oluşturun."
      />
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
                style={{ whiteSpace: 'nowrap', display: 'flex', gap: '0.5rem', alignItems: 'center' }}
              >
                <button
                  className={styles.secondaryBtn}
                  disabled={actualsLoadingId === plan.id}
                  onClick={() => onActuals(plan)}
                  aria-label={`${plan.name} için gerçekleşen verileri göster`}
                  style={{ fontSize: '0.78rem', padding: '0.3rem 0.65rem' }}
                >
                  {actualsLoadingId === plan.id ? '...' : 'Gerçekleşen'}
                </button>
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

  // ---- Plan vs Actuals ----
  const [actualsLoadingId, setActualsLoadingId] = useState<string | null>(null);
  const [actualsData, setActualsData] = useState<PlanActuals | null>(null);
  const [actualsError, setActualsError] = useState<string | null>(null);
  const [actualsPlanName, setActualsPlanName] = useState<string | null>(null);

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
      setPlansError(parseApiError(err));
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
        setPreviewError(parseApiError(err));
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
      setSaveError(parseApiError(err));
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

  // ---- Load plan actuals ----
  async function handleActuals(plan: BudgetPlan) {
    // Toggle off if already showing this plan's actuals
    if (actualsData?.plan_id === plan.id && !actualsLoadingId) {
      setActualsData(null);
      setActualsError(null);
      setActualsPlanName(null);
      return;
    }
    setActualsLoadingId(plan.id);
    setActualsError(null);
    setActualsData(null);
    setActualsPlanName(plan.name);
    try {
      const data = await getPlanActuals(plan.id);
      setActualsData(data);
    } catch (err: unknown) {
      setActualsError(parseApiError(err));
    } finally {
      setActualsLoadingId(null);
    }
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
            onActuals={handleActuals}
            actualsLoadingId={actualsLoadingId}
          />
        </div>

        {/* Plan vs Actuals panel */}
        {(actualsLoadingId !== null || actualsData !== null || actualsError !== null) && (
          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <span className={styles.cardTitle}>
                Plan vs Gerçekleşen
                {actualsPlanName && (
                  <span className={styles.actualsSubtitle}> — {actualsPlanName}</span>
                )}
              </span>
              <button
                className={styles.secondaryBtn}
                onClick={() => {
                  setActualsData(null);
                  setActualsError(null);
                  setActualsPlanName(null);
                  setActualsLoadingId(null);
                }}
                aria-label="Gerçekleşen panelini kapat"
                style={{ fontSize: '0.78rem', padding: '0.3rem 0.65rem' }}
              >
                Kapat
              </button>
            </div>

            {actualsLoadingId !== null ? (
              <div className={styles.previewLoading}>
                <div className={styles.spinner} aria-hidden="true" />
                Gerçekleşen veriler yükleniyor...
              </div>
            ) : actualsError ? (
              <div className={styles.stateBoxSm}>
                <span className={styles.errorText}>{actualsError}</span>
              </div>
            ) : actualsData && actualsData.days_elapsed === 0 ? (
              <div className={styles.stateBoxSm}>
                <span className={styles.muted}>
                  {actualsData.notes[0] ?? 'Plan dönemi henüz başlamadı.'}
                </span>
              </div>
            ) : actualsData ? (
              <PlanActualsPanel actuals={actualsData} />
            ) : null}
          </div>
        )}
      </main>
    </div>
  );
}
