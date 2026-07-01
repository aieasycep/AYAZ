'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getBudgetOptimization,
  type BudgetOptimizationResult,
  type ChannelAllocation,
  type BudgetSuggestion,
} from '@/lib/optimizer-api';
import { parseApiError } from '@/lib/parseApiError';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import BudgetSimulatorPanel from '@/components/BudgetSimulatorPanel';
import styles from './optimizer.module.css';

type BudgetMainTab = 'optimizasyon' | 'senaryo';

// --- Date helpers ---

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getDefaultDates() {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 29);
  return { from: toISODate(from), to: toISODate(to) };
}

// --- Formatters ---

function fmtCurrency(n: number, decimals = 0): string {
  return new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: 'TRY',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function fmtRoas(n: number): string {
  return (
    n.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

function fmtPct(n: number): string {
  return (
    (n * 100).toLocaleString('tr-TR', {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }) + '%'
  );
}

// --- Sub-components ---

function ChannelCard({ item }: { item: ChannelAllocation }) {
  const barWidth = Math.min(100, Math.max(0, item.share_of_spend * 100));
  return (
    <div className={styles.channelCard}>
      <div className={styles.channelName}>{item.channel}</div>
      <div className={styles.channelSpend}>{fmtCurrency(item.spend)}</div>
      <div className={styles.spendBarTrack}>
        <div
          className={styles.spendBarFill}
          style={{ width: `${barWidth}%` }}
        />
      </div>
      <div className={styles.channelMeta}>
        <span className={styles.channelMetaItem}>
          Pay:{' '}
          <span className={styles.channelMetaValue}>{fmtPct(item.share_of_spend)}</span>
        </span>
        <span className={styles.channelMetaItem}>
          ROAS:{' '}
          <span className={styles.channelMetaValue}>{fmtRoas(item.roas)}</span>
        </span>
      </div>
    </div>
  );
}

function SuggestionRow({ s }: { s: BudgetSuggestion }) {
  return (
    <div className={styles.suggestionRow}>
      <div className={styles.suggestionMove}>
        <div className={styles.suggestionMoveLabel}>
          {fmtCurrency(s.amount, 0)} &bull; {s.from_channel} &rarr; {s.to_channel}
        </div>
        {s.projected_conversion_value_delta > 0 && (
          <div className={styles.suggestionProjection}>
            Projeksiyon: +{fmtCurrency(s.projected_conversion_value_delta, 0)} gelir
          </div>
        )}
      </div>
      <div className={styles.suggestionRationale}>{s.rationale}</div>
      <div className={styles.suggestionRoas}>
        <span className={`${styles.roasChip} ${styles.roasFrom}`}>
          {s.from_channel}: {fmtRoas(s.from_roas)}
        </span>
        <span className={`${styles.roasChip} ${styles.roasTo}`}>
          {s.to_channel}: {fmtRoas(s.to_roas)}
        </span>
      </div>
    </div>
  );
}

// --- Page ---

export default function OptimizerPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) router.replace('/login');
  }, [router]);

  // Two sub-tools under one "Bütçe Aracı" roof: the optimizer (default) and the
  // scenario simulator (formerly the standalone /budget-simulator page). A
  // ?tab=senaryo query — used by the old route's redirect — opens the simulator.
  const [mainTab, setMainTab] = useState<BudgetMainTab>('optimizasyon');

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('tab');
    if (t === 'senaryo') setMainTab('senaryo');
  }, []);

  const selectMainTab = useCallback((t: BudgetMainTab) => {
    setMainTab(t);
    const url = t === 'senaryo' ? '/optimizer?tab=senaryo' : '/optimizer';
    window.history.replaceState(null, '', url);
  }, []);

  const defaults = getDefaultDates();
  const [dateFrom, setDateFrom] = useState(defaults.from);
  const [dateTo, setDateTo] = useState(defaults.to);
  const [maxShiftPct, setMaxShiftPct] = useState<number>(20);

  const [result, setResult] = useState<BudgetOptimizationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasCalculated, setHasCalculated] = useState(false);

  const runOptimization = useCallback(
    async (from: string, to: string, shift: number) => {
      setLoading(true);
      setError(null);
      try {
        const data = await getBudgetOptimization({
          date_from: from,
          date_to: to,
          max_shift_pct: shift,
        });
        setResult(data);
        setHasCalculated(true);
      } catch (err: unknown) {
        setError(parseApiError(err));
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  function handleCalculate() {
    runOptimization(dateFrom, dateTo, maxShiftPct);
  }

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Bütçe Aracı</h1>
            <p className={styles.pageSubtitle}>
              Bütçenizi optimize edin veya kanallar arası senaryoları anında test edin.
            </p>
          </div>
        </div>

        {/* Sub-tool tabs: optimizasyon | senaryo */}
        <div className={styles.mainTabs} role="tablist" aria-label="Bütçe aracı bölümleri">
          <button
            type="button"
            role="tab"
            aria-selected={mainTab === 'optimizasyon'}
            className={`${styles.mainTab} ${mainTab === 'optimizasyon' ? styles.mainTabActive : ''}`}
            onClick={() => selectMainTab('optimizasyon')}
          >
            Optimizasyon
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mainTab === 'senaryo'}
            className={`${styles.mainTab} ${mainTab === 'senaryo' ? styles.mainTabActive : ''}`}
            onClick={() => selectMainTab('senaryo')}
          >
            Senaryo Simülatörü
          </button>
        </div>

        {mainTab === 'senaryo' && <BudgetSimulatorPanel />}

        {mainTab === 'optimizasyon' && (
        <>
        {/* Controls section */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Parametreler</h2>
          </div>
          <div className={styles.toolbar}>
            <div className={styles.dateGroup}>
              <label className={styles.dateLabel} htmlFor="opt-from">
                Başlangıç
              </label>
              <input
                id="opt-from"
                type="date"
                className={styles.dateInput}
                value={dateFrom}
                max={dateTo}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div className={styles.dateGroup}>
              <label className={styles.dateLabel} htmlFor="opt-to">
                Bitiş
              </label>
              <input
                id="opt-to"
                type="date"
                className={styles.dateInput}
                value={dateTo}
                min={dateFrom}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
            <div className={styles.shiftGroup}>
              <label className={styles.shiftLabel} htmlFor="opt-shift">
                MAX KAYDIRMA %{' '}
                <span
                  className={styles.tooltipAnchor}
                  aria-label="Bir kanaldan diğerine aktarılabilecek maksimum bütçe yüzdesi. Örnek: 20 girilirse mevcut harcamanın en fazla %20'si taşınabilir."
                  role="tooltip"
                  tabIndex={0}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 16 16"
                    fill="none"
                    aria-hidden="true"
                    xmlns="http://www.w3.org/2000/svg"
                    className={styles.tooltipIcon}
                  >
                    <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.5" />
                    <path d="M8 7v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    <circle cx="8" cy="4.5" r="0.75" fill="currentColor" />
                  </svg>
                  <span className={styles.tooltipPopup} role="presentation">
                    Bir kanaldan diğerine aktarılabilecek maksimum bütçe yüzdesi. Örn: 20 girilirse mevcut harcamanın en fazla %20&apos;si taşınabilir.
                  </span>
                </span>
              </label>
              <input
                id="opt-shift"
                type="number"
                className={styles.shiftInput}
                value={maxShiftPct}
                min={1}
                max={100}
                step={1}
                onChange={(e) => setMaxShiftPct(Number(e.target.value))}
              />
            </div>
            <button
              className={styles.calcBtn}
              onClick={handleCalculate}
              disabled={loading}
            >
              {loading ? 'Hesaplanıyor...' : 'Optimizasyonu Hesapla'}
            </button>
          </div>
        </section>

        {/* Results */}
        {!hasCalculated && !loading && !error && (
          <>
            <section className={styles.section}>
              <div className={styles.stateBox}>
                <span className={styles.muted}>
                  Parametreleri ayarlayıp &ldquo;Optimizasyonu Hesapla&rdquo; butonuna basın.
                </span>
              </div>
            </section>

            {/* Ghost preview — shows the output shape before first run */}
            <div className={styles.previewGhost} aria-hidden="true">
              <SectionCard title="Mevcut Dağılım (Önizleme)">
                <div className={styles.previewAllocationGrid}>
                  {['Kanal A', 'Kanal B', 'Kanal C'].map((name) => (
                    <div key={name} className={styles.previewChannelCard}>
                      <div className={styles.previewLabel}>{name}</div>
                      <div className={styles.previewValue}>₺ — —</div>
                      <div className={styles.previewBar}>
                        <div className={styles.previewBarFill} style={{ width: '55%' }} />
                      </div>
                      <div className={styles.previewMeta}>Pay: —%  ROAS: —x</div>
                    </div>
                  ))}
                </div>
              </SectionCard>

              <SectionCard title="Öneriler (Önizleme)">
                <div className={styles.previewSuggestions}>
                  {[1, 2].map((i) => (
                    <div key={i} className={styles.previewSuggestionRow}>
                      <div className={styles.previewSuggestionMove}>₺ — —  Kanal X &rarr; Kanal Y</div>
                      <div className={styles.previewSuggestionRationale}>
                        Daha yüksek ROAS potansiyeline sahip kanala yönlendirme önerisi
                      </div>
                      <div className={styles.previewChips}>
                        <span className={styles.previewChipFrom}>X: —x</span>
                        <span className={styles.previewChipTo}>Y: —x</span>
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>
            </div>
          </>
        )}

        {loading && (
          <section className={styles.section}>
            <div className={styles.stateBox}>
              <span className={styles.muted}>Optimizasyon hesaplanıyor...</span>
            </div>
          </section>
        )}

        {error && (
          <section className={styles.section}>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={handleCalculate}>
                Tekrar Dene
              </button>
            </div>
          </section>
        )}

        {result && !loading && (
          <>
            {/* Current allocation */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>
                  Mevcut Dağılım
                  {result.current_allocation.length > 0
                    ? ` (${result.current_allocation.length} kanal)`
                    : ''}
                </h2>
              </div>
              {result.current_allocation.length === 0 ? (
                <div className={styles.stateBox}>
                  <span className={styles.muted}>
                    Bu dönem için kanal verisi bulunamadı.
                  </span>
                </div>
              ) : (
                <div className={styles.allocationGrid}>
                  {result.current_allocation.map((item) => (
                    <ChannelCard key={item.channel} item={item} />
                  ))}
                </div>
              )}
            </section>

            {/* Suggestions */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>
                  Öneriler
                  {result.suggestions.length > 0
                    ? ` (${result.suggestions.length})`
                    : ''}
                </h2>
              </div>

              {/* Summary banner */}
              {result.suggestions.length > 0 && (
                <div className={styles.summaryBanner}>
                  <div className={styles.summaryItem}>
                    <span className={styles.summaryLabel}>Toplam Kaydırma</span>
                    <span className={styles.summaryValue}>
                      {fmtCurrency(result.summary.total_shift, 0)}
                    </span>
                  </div>
                  <div className={styles.summaryItem}>
                    <span className={styles.summaryLabel}>Projeksiyon Artışı</span>
                    <span className={styles.summaryValue}>
                      +{fmtCurrency(result.summary.projected_total_uplift, 0)}
                    </span>
                  </div>
                </div>
              )}

              {result.suggestions.length === 0 ? (
                <div className={styles.stateBox}>
                  <span className={styles.muted}>
                    Bu dönem ve parametreler için yeniden dağılım önerisi bulunmuyor.
                  </span>
                </div>
              ) : (
                <div className={styles.suggestionList}>
                  {result.suggestions.map((s, idx) => (
                    <SuggestionRow key={idx} s={s} />
                  ))}
                </div>
              )}

              {/* Caveat */}
              {result.caveat && (
                <p className={styles.caveat}>{result.caveat}</p>
              )}
            </section>
          </>
        )}
        </>
        )}
      </main>
    </div>
  );
}
