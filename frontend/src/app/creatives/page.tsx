'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken, downloadCsv } from '@/lib/api';
import { channelLabel } from '@/lib/channels';
import {
  getCreativesPerformance,
  type AdPerformance,
  type AdSortField,
  type CreativesPerformanceResponse,
} from '@/lib/creatives-api';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import DateRangePresets, {
  detectPreset,
  type PresetKey,
} from '@/components/DateRangePresets';
import { parseApiError } from '@/lib/parseApiError';
import styles from './creatives.module.css';

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

function fmtNum(n: number): string {
  return new Intl.NumberFormat('tr-TR').format(Math.round(n));
}

function fmtPct(n: number): string {
  return (
    '%' +
    (n * 100).toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

function fmtRoas(n: number): string {
  return (
    n.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

// --- Sort options ---

interface SortOption {
  value: AdSortField;
  label: string;
}

const SORT_OPTIONS: SortOption[] = [
  { value: 'spend', label: 'Harcama' },
  { value: 'roas', label: 'ROAS' },
  { value: 'ctr', label: 'CTR' },
  { value: 'conversions', label: 'Dönüşüm' },
  { value: 'impressions', label: 'Gösterim' },
  { value: 'clicks', label: 'Tıklama' },
  { value: 'cpc', label: 'CPC' },
];

// Column defs for the sortable table
interface ColDef {
  key: AdSortField | 'ad_name' | 'campaign_name' | 'channel';
  label: string;
  align: 'left' | 'right';
  sortable: boolean;
  sortKey?: AdSortField;
  render: (ad: AdPerformance) => string | React.ReactNode;
}

// --- Ad table column definitions ---

const COLUMNS: ColDef[] = [
  {
    key: 'ad_name',
    label: 'Reklam',
    align: 'left',
    sortable: false,
    render: (ad) => (
      <div>
        <div className={styles.adName} title={ad.ad_name}>{ad.ad_name}</div>
        <div className={styles.campaignName} title={ad.campaign_name}>{ad.campaign_name}</div>
      </div>
    ),
  },
  {
    key: 'channel',
    label: 'Kanal',
    align: 'left',
    sortable: false,
    render: (ad) => <span className={styles.channelBadge}>{channelLabel(ad.channel)}</span>,
  },
  {
    key: 'spend',
    label: 'Harcama',
    align: 'right',
    sortable: true,
    sortKey: 'spend',
    render: (ad) => fmtCurrency(ad.spend),
  },
  {
    key: 'roas',
    label: 'ROAS',
    align: 'right',
    sortable: true,
    sortKey: 'roas',
    render: (ad) => {
      const cls =
        ad.roas >= 2
          ? styles.roasGood
          : ad.roas < 1
          ? styles.roasBad
          : styles.roasNeutral;
      return <span className={cls}>{fmtRoas(ad.roas)}</span>;
    },
  },
  {
    key: 'ctr',
    label: 'CTR',
    align: 'right',
    sortable: true,
    sortKey: 'ctr',
    render: (ad) => fmtPct(ad.ctr),
  },
  {
    key: 'conversions',
    label: 'Dönüşüm',
    align: 'right',
    sortable: true,
    sortKey: 'conversions',
    render: (ad) => fmtNum(ad.conversions),
  },
  {
    key: 'cpc',
    label: 'CPC',
    align: 'right',
    sortable: true,
    sortKey: 'cpc',
    render: (ad) => fmtCurrency(ad.cpc, 2),
  },
];

// --- Component ---

export default function CreativesPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  const defaults = getDefaultDates();
  const [dateFrom, setDateFrom] = useState(defaults.from);
  const [dateTo, setDateTo] = useState(defaults.to);
  const [appliedFrom, setAppliedFrom] = useState(defaults.from);
  const [appliedTo, setAppliedTo] = useState(defaults.to);
  const [sort, setSort] = useState<AdSortField>('spend');

  // Track which preset is currently active (null = custom/no match)
  const [activePreset, setActivePreset] = useState<PresetKey | null>(
    () => detectPreset(defaults.from, defaults.to),
  );

  const [data, setData] = useState<CreativesPerformanceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // CSV export state
  const [csvLoading, setCsvLoading] = useState(false);
  const [csvError, setCsvError] = useState<string | null>(null);

  async function handleCsvExport() {
    setCsvLoading(true);
    setCsvError(null);
    try {
      await downloadCsv(
        '/api/v1/creatives/export',
        { date_from: appliedFrom, date_to: appliedTo },
        `kreatifler-${appliedFrom}-${appliedTo}.csv`,
      );
    } catch (err: unknown) {
      setCsvError(parseApiError(err));
    } finally {
      setCsvLoading(false);
    }
  }

  const fetchData = useCallback(async (from: string, to: string, s: AdSortField) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getCreativesPerformance({ date_from: from, date_to: to, sort: s });
      setData(result);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    if (!getToken()) return;
    fetchData(appliedFrom, appliedTo, sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyDates() {
    setAppliedFrom(dateFrom);
    setAppliedTo(dateTo);
    setActivePreset(detectPreset(dateFrom, dateTo));
    fetchData(dateFrom, dateTo, sort);
  }

  function handlePresetSelect(from: string, to: string) {
    setDateFrom(from);
    setDateTo(to);
    setAppliedFrom(from);
    setAppliedTo(to);
    setActivePreset(detectPreset(from, to));
    fetchData(from, to, sort);
  }

  function handleSortChange(newSort: AdSortField) {
    setSort(newSort);
    fetchData(appliedFrom, appliedTo, newSort);
  }

  function handleColSort(sortKey: AdSortField) {
    handleSortChange(sortKey);
  }

  const ads = data?.ads ?? [];
  const topAds = data?.top ?? [];
  const bottomAds = data?.bottom ?? [];
  const commentary = data?.commentary ?? '';

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>Kreatifler</h1>
          <p className={styles.pageSubtitle}>Reklam kreatiflerinin performans analizi</p>
        </div>

        {/* Date bar */}
        <section className={styles.dateBar}>
          {/* Quick presets — full-width row above date inputs */}
          <div className={styles.presetsRow}>
            <DateRangePresets
              onSelect={handlePresetSelect}
              activePreset={activePreset}
            />
          </div>

          <div className={styles.dateGroup}>
            <label className={styles.dateLabel} htmlFor="cr-date-from">
              Başlangıç
            </label>
            <input
              id="cr-date-from"
              type="date"
              className={styles.dateInput}
              value={dateFrom}
              max={dateTo}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </div>
          <div className={styles.dateGroup}>
            <label className={styles.dateLabel} htmlFor="cr-date-to">
              Bitiş
            </label>
            <input
              id="cr-date-to"
              type="date"
              className={styles.dateInput}
              value={dateTo}
              min={dateFrom}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </div>
          <button className={styles.applyBtn} onClick={applyDates}>
            Uygula
          </button>

          {/* CSV export */}
          <div className={styles.csvGroup}>
            <button
              className={styles.csvBtn}
              onClick={handleCsvExport}
              disabled={csvLoading}
            >
              {csvLoading ? 'İndiriliyor...' : 'CSV İndir'}
            </button>
            {csvError && (
              <span className={styles.csvError}>{csvError}</span>
            )}
          </div>
        </section>

        {/* Loading */}
        {loading && (
          <div className={styles.card}>
            <div className={styles.stateBox}>
              <span className={styles.muted}>Yükleniyor...</span>
            </div>
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className={styles.card}>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
            </div>
          </div>
        )}

        {!loading && !error && data && (
          <>
            {/* AI commentary panel */}
            {commentary && (
              <div className={styles.commentaryCard}>
                <div className={styles.commentaryHeader}>
                  <span className={styles.commentaryBadge}>AI Yorumu</span>
                  <span className={styles.commentaryTitle}>Ne iyi gidiyor, nerede bütçe boşa gidiyor?</span>
                </div>
                <p className={styles.commentaryText}>{commentary}</p>
              </div>
            )}

            {/* Top / Bottom highlights */}
            {(topAds.length > 0 || bottomAds.length > 0) && (
              <div className={styles.highlightsRow}>
                {/* En İYİ */}
                <SectionCard
                  title=""
                  right={<span className={styles.badgeTop}>EN İYİ</span>}
                >
                  <div className={styles.highlightCardInner}>
                    <span className={styles.highlightTitle}>En Yüksek ROAS</span>
                    {topAds.length === 0 ? (
                      <div className={styles.stateBox}>
                        <span className={styles.muted}>Veri yok</span>
                      </div>
                    ) : (
                      <ul className={styles.highlightList}>
                        {topAds.map((ad) => (
                          <li key={ad.ad_id} className={styles.highlightItem}>
                            <span className={styles.highlightAdName} title={ad.ad_name}>
                              {ad.ad_name}
                              <span className={styles.highlightChannel}> · {channelLabel(ad.channel)}</span>
                            </span>
                            <span className={styles.roasGood}>{fmtRoas(ad.roas)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </SectionCard>

                {/* EN KÖTÜ */}
                <SectionCard
                  title=""
                  right={<span className={styles.badgeBottom}>EN KÖTÜ</span>}
                >
                  <div className={styles.highlightCardInner}>
                    <span className={styles.highlightTitle}>En Düşük ROAS</span>
                    {bottomAds.length === 0 ? (
                      <div className={styles.stateBox}>
                        <span className={styles.muted}>Veri yok</span>
                      </div>
                    ) : (
                      <ul className={styles.highlightList}>
                        {bottomAds.map((ad) => (
                          <li key={ad.ad_id} className={styles.highlightItem}>
                            <span className={styles.highlightAdName} title={ad.ad_name}>
                              {ad.ad_name}
                              <span className={styles.highlightChannel}> · {channelLabel(ad.channel)}</span>
                            </span>
                            <span className={styles.roasBad}>{fmtRoas(ad.roas)}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </SectionCard>
              </div>
            )}

            {/* Main ad table */}
            <SectionCard
              title="Reklam Tablosu"
              right={
                <div className={styles.sortPicker}>
                  <span className={styles.sortLabel}>Sırala:</span>
                  <select
                    className={styles.sortSelect}
                    value={sort}
                    onChange={(e) => handleSortChange(e.target.value as AdSortField)}
                  >
                    {SORT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </div>
              }
            >
              {ads.length === 0 ? (
                <div className={styles.stateBox}>
                  <span className={styles.muted}>
                    Bu dönem için reklam verisi bulunmuyor.
                  </span>
                </div>
              ) : (
                <div className={styles.tableWrap}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        {COLUMNS.map((col) => (
                          <th
                            key={col.key}
                            className={[
                              styles.th,
                              col.align === 'right' ? styles.right : '',
                              col.sortable ? styles.thSortable : '',
                              col.sortable && col.sortKey === sort ? styles.thActive : '',
                            ]
                              .filter(Boolean)
                              .join(' ')}
                            onClick={
                              col.sortable && col.sortKey
                                ? () => handleColSort(col.sortKey as AdSortField)
                                : undefined
                            }
                          >
                            {col.label}
                            {col.sortable && col.sortKey === sort && (
                              <span className={styles.sortIndicator}>↓</span>
                            )}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {ads.map((ad) => (
                        <tr key={ad.ad_id} className={styles.row}>
                          {COLUMNS.map((col) => (
                            <td
                              key={col.key}
                              className={[
                                styles.td,
                                col.align === 'right' ? styles.right : '',
                              ]
                                .filter(Boolean)
                                .join(' ')}
                            >
                              {col.render(ad)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>
          </>
        )}

        {/* Empty — no data at all */}
        {!loading && !error && !data && (
          <div className={styles.card}>
            <div className={styles.stateBox}>
              <span className={styles.muted}>Veri bulunamadı.</span>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
