'use client';

// Budget scenario simulator, extracted from the former /budget-simulator page so
// it can live as the "Senaryo" tab inside the merged /optimizer ("Bütçe Aracı")
// screen. Renders only the inner content — no AppNav/shell/page-header — because
// the host page provides those. Behaviour is identical to the standalone page.

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { channelColor } from '@/lib/chartColors';
import {
  getBaseline,
  simulate,
  type SimBaseline,
  type SimResult,
} from '@/lib/budget-simulator-api';
import { parseApiError } from '@/lib/parseApiError';
import styles from '@/app/budget-simulator/budget-simulator.module.css';

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

const tryFmt = new Intl.NumberFormat('tr-TR', {
  style: 'currency',
  currency: 'TRY',
  maximumFractionDigits: 0,
});

function fmtCurrency(n: number): string {
  return tryFmt.format(n);
}

function fmtNumber(n: number): string {
  // Count-type metrics (impressions/clicks/conversions) are linear projections
  // that come out fractional; show them as whole units for a clean read.
  return Math.round(n).toLocaleString('tr-TR', { maximumFractionDigits: 0 });
}

function fmtRoas(n: number): string {
  return (
    n.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

function fmtDeltaPct(pct: number | null | undefined): {
  text: string;
  dir: 'up' | 'down' | 'neutral';
} {
  if (pct === null || pct === undefined)
    return { text: '—', dir: 'neutral' };
  const abs = Math.abs(pct).toLocaleString('tr-TR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  if (pct > 0) return { text: `▲ %${abs}`, dir: 'up' };
  if (pct < 0) return { text: `▼ %${abs}`, dir: 'down' };
  return { text: `%${abs}`, dir: 'neutral' };
}

function fmtSpendDeltaPct(pct: number): string {
  const abs = Math.abs(pct).toLocaleString('tr-TR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  if (pct > 0) return `+%${abs}`;
  if (pct < 0) return `-%${abs}`;
  return `%${abs}`;
}

// ---------------------------------------------------------------------------
// Delta badge
// ---------------------------------------------------------------------------

function DeltaBadge({ pct }: { pct: number | null | undefined }) {
  const { text, dir } = fmtDeltaPct(pct);
  const cls =
    dir === 'up'
      ? styles.deltaUp
      : dir === 'down'
      ? styles.deltaDown
      : styles.deltaNeutral;
  return <span className={`${styles.deltaBadge} ${cls}`}>{text}</span>;
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function LoadingSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonAllocation}`} />
      <div className={styles.skeletonKpiGrid}>
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className={`${styles.skeleton} ${styles.skeletonCard}`} />
        ))}
      </div>
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export default function BudgetSimulatorPanel() {
  const [baseline, setBaseline] = useState<SimBaseline | null>(null);
  const [allocations, setAllocations] = useState<Record<string, number>>({});
  const [simResult, setSimResult] = useState<SimResult | null>(null);
  const [loadingBaseline, setLoadingBaseline] = useState(true);
  const [baselineError, setBaselineError] = useState<string | null>(null);
  const [simPending, setSimPending] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch baseline on mount
  const fetchBaseline = useCallback(async () => {
    setLoadingBaseline(true);
    setBaselineError(null);
    try {
      const data = await getBaseline(30);
      setBaseline(data);
      // Pre-fill allocations from baseline
      const init: Record<string, number> = {};
      for (const ch of data.channels) {
        init[ch.key] = ch.spend;
      }
      setAllocations(init);
    } catch (err: unknown) {
      setBaselineError(
        parseApiError(err),
      );
    } finally {
      setLoadingBaseline(false);
    }
  }, []);

  useEffect(() => {
    fetchBaseline();
  }, [fetchBaseline]);

  // Run simulation on allocation change (debounced 300ms)
  const runSimulate = useCallback(
    async (allocs: Record<string, number>) => {
      setSimPending(true);
      setSimError(null);
      try {
        const result = await simulate(allocs, 30);
        setSimResult(result);
      } catch (err: unknown) {
        setSimError(
          parseApiError(err),
        );
      } finally {
        setSimPending(false);
      }
    },
    [],
  );

  // Trigger debounced simulation whenever allocations change (after baseline loaded)
  useEffect(() => {
    if (!baseline) return;
    if (Object.keys(allocations).length === 0) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      runSimulate(allocations);
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [allocations, baseline, runSimulate]);

  // Reset to baseline
  function resetToBaseline() {
    if (!baseline) return;
    const init: Record<string, number> = {};
    for (const ch of baseline.channels) {
      init[ch.key] = ch.spend;
    }
    setAllocations(init);
  }

  // Distribute total evenly
  function distributeEvenly() {
    if (!baseline) return;
    const total = Object.values(allocations).reduce((s, v) => s + v, 0);
    const n = baseline.channels.length;
    if (n === 0) return;
    const each = Math.round(total / n);
    const init: Record<string, number> = {};
    for (const ch of baseline.channels) {
      init[ch.key] = each;
    }
    setAllocations(init);
  }

  function handleInputChange(key: string, value: number) {
    const clamped = Math.max(0, value);
    setAllocations((prev) => ({ ...prev, [key]: clamped }));
  }

  // Compute total allocation
  const totalAllocation = Object.values(allocations).reduce((s, v) => s + v, 0);

  // Build chart data: baseline vs senaryo per channel (Dönüşüm + Gelir)
  const chartData = simResult
    ? simResult.channels.map((ch) => {
        const baselineCh = baseline?.channels.find((b) => b.key === ch.key);
        return {
          name: ch.label,
          channelKey: ch.key,
          'Baz Dönüşüm': baselineCh?.conversions ?? 0,
          'Senaryo Dönüşüm': ch.conversions,
        };
      })
    : [];

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      <p className={styles.pageSubtitle}>
        Kanallar arası bütçeyi değiştirin, geçmiş verimliliğe göre tahmini
        sonucu anında görün.
      </p>

      {loadingBaseline ? (
        <LoadingSkeleton />
      ) : baselineError ? (
        <div className={styles.sectionCard}>
          <div className={styles.stateBox}>
            <span className={styles.errorText}>{baselineError}</span>
            <br />
            <button className={styles.retryBtn} onClick={fetchBaseline}>
              Tekrar Dene
            </button>
          </div>
        </div>
      ) : baseline ? (
        <>
          {/* -------- Allocation panel -------- */}
          <div className={styles.sectionCard}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionTitle}>Bütçe Dağılımı</span>
              <span style={{ fontSize: '0.8125rem', color: 'var(--color-text-muted)' }}>
                {baseline.period.date_from} — {baseline.period.date_to}
              </span>
            </div>
            <div className={styles.sectionBody}>
              {/* Total readout */}
              <div className={styles.totalBudgetRow}>
                <span className={styles.totalBudgetLabel}>Toplam Bütçe</span>
                <span className={styles.totalBudgetValue}>
                  {fmtCurrency(totalAllocation)}
                </span>
              </div>

              {/* Per-channel rows */}
              <div className={styles.channelRows}>
                {baseline.channels.map((ch) => {
                  const currentVal = allocations[ch.key] ?? ch.spend;
                  const maxSlider = Math.max(ch.spend * 3, 10000);
                  return (
                    <div key={ch.key} className={styles.channelRow}>
                      <div className={styles.channelRowTop}>
                        <div>
                          <div className={styles.channelLabel}>{ch.label}</div>
                          <div className={styles.channelBaselineRef}>
                            Baz: {fmtCurrency(ch.spend)} · %
                            {ch.spend_share_pct.toLocaleString('tr-TR', {
                              maximumFractionDigits: 1,
                            })}
                          </div>
                        </div>
                        <div className={styles.channelInputGroup}>
                          <input
                            type="range"
                            className={styles.channelSlider}
                            min={0}
                            max={maxSlider}
                            step={1000}
                            value={currentVal}
                            onChange={(e) =>
                              handleInputChange(ch.key, Number(e.target.value))
                            }
                            aria-label={`${ch.label} bütçe kaydırıcı`}
                          />
                          <input
                            type="number"
                            className={styles.channelInput}
                            min={0}
                            step={1000}
                            value={currentVal}
                            onChange={(e) =>
                              handleInputChange(ch.key, Number(e.target.value))
                            }
                            aria-label={`${ch.label} bütçe miktarı`}
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Action buttons */}
              <div className={styles.allocationActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={resetToBaseline}
                >
                  Mevcut dağılıma sıfırla
                </button>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={distributeEvenly}
                >
                  Eşit dağıt
                </button>
              </div>
            </div>
          </div>

          {/* -------- Projected KPI cards -------- */}
          {(simResult || simPending) && (
            <div
              className={`${styles.kpiGrid} ${simPending ? styles.kpiPending : ''}`}
            >
              {simResult && (
                <>
                  <div className={styles.kpiCard}>
                    <div className={styles.kpiLabel}>Harcama</div>
                    <div className={styles.kpiValue}>
                      {fmtCurrency(simResult.projected_totals.spend)}
                    </div>
                    <DeltaBadge pct={null} />
                  </div>

                  <div className={styles.kpiCard}>
                    <div className={styles.kpiLabel}>Gösterim</div>
                    <div className={styles.kpiValue}>
                      {fmtNumber(simResult.projected_totals.impressions)}
                    </div>
                    <DeltaBadge pct={simResult.deltas.impressions_pct} />
                  </div>

                  <div className={styles.kpiCard}>
                    <div className={styles.kpiLabel}>Tıklama</div>
                    <div className={styles.kpiValue}>
                      {fmtNumber(simResult.projected_totals.clicks)}
                    </div>
                    <DeltaBadge pct={simResult.deltas.clicks_pct} />
                  </div>

                  <div className={styles.kpiCard}>
                    <div className={styles.kpiLabel}>Dönüşüm</div>
                    <div className={styles.kpiValue}>
                      {fmtNumber(simResult.projected_totals.conversions)}
                    </div>
                    <DeltaBadge pct={simResult.deltas.conversions_pct} />
                  </div>

                  <div className={styles.kpiCard}>
                    <div className={styles.kpiLabel}>Gelir</div>
                    <div className={styles.kpiValue}>
                      {fmtCurrency(simResult.projected_totals.conversion_value)}
                    </div>
                    <DeltaBadge pct={simResult.deltas.conversion_value_pct} />
                  </div>

                  <div className={styles.kpiCard}>
                    <div className={styles.kpiLabel}>ROAS</div>
                    <div className={styles.kpiValueRoas}>
                      {fmtRoas(simResult.projected_totals.roas)}
                    </div>
                    <DeltaBadge pct={simResult.deltas.roas_pct} />
                  </div>
                </>
              )}
            </div>
          )}

          {simError && (
            <div className={styles.sectionCard}>
              <div className={styles.stateBox}>
                <span className={styles.errorText}>{simError}</span>
                <br />
                <button
                  className={styles.retryBtn}
                  onClick={() => runSimulate(allocations)}
                >
                  Tekrar Dene
                </button>
              </div>
            </div>
          )}

          {/* -------- Comparison chart -------- */}
          {simResult && chartData.length > 0 && (
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>
                  Baz Senaryo Karşılaştırması — Dönüşüm (Kanallar)
                </span>
              </div>
              <div className={styles.chartWrap}>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart
                    data={chartData}
                    margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
                    barCategoryGap="30%"
                    barGap={4}
                  >
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="var(--color-border)"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }}
                      tickLine={false}
                      axisLine={false}
                      width={40}
                      tickFormatter={(v: number) =>
                        v >= 1000
                          ? `${(v / 1000).toLocaleString('tr-TR', { maximumFractionDigits: 1 })}B`
                          : String(v)
                      }
                    />
                    <Tooltip
                      contentStyle={{
                        borderRadius: 8,
                        border: '1px solid var(--color-border)',
                        fontSize: 12,
                        background: 'var(--color-surface)',
                        color: 'var(--color-text)',
                      }}
                      formatter={(value: number) => [
                        fmtNumber(value),
                        undefined,
                      ]}
                    />
                    <Legend
                      wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                    />
                    <Bar
                      dataKey="Baz Dönüşüm"
                      radius={[4, 4, 0, 0]}
                      isAnimationActive={false}
                    >
                      {chartData.map((entry) => (
                        <Cell
                          key={`base-${entry.channelKey}`}
                          fill={channelColor(entry.channelKey)}
                          fillOpacity={0.35}
                        />
                      ))}
                    </Bar>
                    <Bar
                      dataKey="Senaryo Dönüşüm"
                      radius={[4, 4, 0, 0]}
                      isAnimationActive={false}
                    >
                      {chartData.map((entry) => (
                        <Cell
                          key={`scenario-${entry.channelKey}`}
                          fill={channelColor(entry.channelKey)}
                          fillOpacity={1}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* -------- Per-channel table -------- */}
          {simResult && (
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Kanal Projeksiyon Detayı</span>
              </div>
              <div className={styles.tableWrap}>
                <table className={styles.channelTable}>
                  <thead>
                    <tr>
                      <th>Kanal</th>
                      <th className={styles.numCol}>Planlanan Harcama</th>
                      <th className={styles.numCol}>Baz Farkı</th>
                      <th className={styles.numCol}>Tahmini Dönüşüm</th>
                      <th className={styles.numCol}>Tahmini Gelir</th>
                      <th className={styles.numCol}>ROAS</th>
                    </tr>
                  </thead>
                  <tbody>
                    {simResult.channels.map((ch) => {
                      const deltaPct = ch.spend_delta_pct;
                      const deltaClass =
                        deltaPct > 0
                          ? styles.deltaPositive
                          : deltaPct < 0
                          ? styles.deltaNegativeText
                          : '';
                      return (
                        <tr key={ch.key}>
                          <td>
                            <span style={{ fontWeight: 600 }}>{ch.label}</span>
                          </td>
                          <td className={styles.numCol}>
                            {fmtCurrency(ch.spend)}
                          </td>
                          <td className={`${styles.numCol} ${deltaClass}`}>
                            {fmtSpendDeltaPct(deltaPct)}
                          </td>
                          <td className={styles.numCol}>
                            {fmtNumber(ch.conversions)}
                          </td>
                          <td className={styles.numCol}>
                            {fmtCurrency(ch.conversion_value)}
                          </td>
                          <td className={`${styles.numCol} ${styles.roasVal}`}>
                            {fmtRoas(ch.roas)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* -------- Assumptions -------- */}
          {simResult && simResult.assumptions.length > 0 && (
            <div className={styles.assumptionsBlock}>
              <div className={styles.assumptionsTitle}>Varsayımlar</div>
              {simResult.assumptions.map((a, i) => (
                <div key={i} className={styles.assumptionItem}>
                  <span className={styles.assumptionDot} aria-hidden="true" />
                  {a}
                </div>
              ))}
            </div>
          )}

          {/* -------- Planning CTA -------- */}
          {simResult && (
            <div className={styles.planCtaRow}>
              <Link href="/planning" className={styles.btnPrimary}>
                Senaryoyu plana çevir
              </Link>
            </div>
          )}
        </>
      ) : null}
    </>
  );
}
