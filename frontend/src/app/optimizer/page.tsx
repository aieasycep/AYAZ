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
import AppNav from '@/components/AppNav';
import styles from './optimizer.module.css';

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
        setError(err instanceof Error ? err.message : 'Optimizasyon hesaplanamadı');
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
            <h1 className={styles.pageTitle}>Bütçe Optimizasyonu</h1>
            <p className={styles.pageSubtitle}>
              Kanallar arası bütçe dağılımını optimize ederek dönüşüm değerini artırın.
            </p>
          </div>
        </div>

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
                Max Kaydırma %
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
          <section className={styles.section}>
            <div className={styles.stateBox}>
              <span className={styles.muted}>
                Parametreleri ayarlayıp "Optimizasyonu Hesapla" butonuna basın.
              </span>
            </div>
          </section>
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
                      +{fmtCurrency(result.summary.projected_uplift, 0)}
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
      </main>
    </div>
  );
}
