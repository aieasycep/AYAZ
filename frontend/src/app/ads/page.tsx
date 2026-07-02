'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { getToken, downloadCsv } from '@/lib/api';
import {
  getCampaigns,
  getCampaignDetail,
  getRecommendations,
  type Campaign,
  type CampaignDetail,
  type Recommendation,
  type CampaignStatus,
  type CampaignSortField,
  type RecommendationSeverity,
} from '@/lib/ads-api';
import TimeSeriesChart from '@/components/TimeSeriesChart';
import AppNav from '@/components/AppNav';
import ErrorBoundary from '@/components/ErrorBoundary';
import { LoadingState, ErrorState, EmptyState } from '@/components/StateViews';
import DateRangePresets, {
  detectPreset,
  type PresetKey,
} from '@/components/DateRangePresets';
import { parseApiError } from '@/lib/parseApiError';
import { applyFocus, filterCampaignsByName } from '@/lib/ads-focus';
import { channelLabel } from '@/lib/channels';
import styles from './ads.module.css';

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
    (n * 100).toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + '%'
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

// --- Status badge ---

function statusLabel(s: CampaignStatus): string {
  switch (s) {
    case 'active': return 'Aktif';
    case 'paused': return 'Duraklatıldı';
    case 'ended': return 'Bitti';
    case 'draft': return 'Taslak';
  }
}

function statusBadgeClass(s: CampaignStatus): string {
  switch (s) {
    case 'active': return styles.badgeActive;
    case 'paused': return styles.badgePaused;
    case 'ended': return styles.badgeEnded;
    case 'draft': return styles.badgeDraft;
  }
}

// --- ROAS coloring — green above 2x target, red below ---

function roasClass(roas: number): string {
  if (roas >= 2) return styles.roasGood;
  if (roas < 1) return styles.roasBad;
  return '';
}

// --- Recommendation grouping ---

interface RecoGroup {
  campaign_id: string;
  campaign_name: string;
  items: Recommendation[];
}

function groupRecos(recos: Recommendation[]): RecoGroup[] {
  const map = new Map<string, RecoGroup>();
  for (const r of recos) {
    const key = r.campaign_id;
    if (!map.has(key)) {
      map.set(key, { campaign_id: key, campaign_name: r.campaign_name, items: [] });
    }
    map.get(key)!.items.push(r);
  }
  return Array.from(map.values());
}

// --- Recommendation severity ---

function recoSeverityLabel(s: RecommendationSeverity): string {
  switch (s) {
    case 'critical': return 'Kritik';
    case 'warning': return 'Uyarı';
    case 'info': return 'Bilgi';
  }
}

function recoSeverityClass(s: RecommendationSeverity): string {
  switch (s) {
    case 'critical': return styles.badgeCritical;
    case 'warning': return styles.badgeWarning;
    case 'info': return styles.badgeInfo;
  }
}

// --- Sortable column header ---

interface SortConfig {
  field: CampaignSortField | null;
  dir: 'asc' | 'desc';
}

function sortCampaigns(
  campaigns: Campaign[],
  config: SortConfig,
): Campaign[] {
  if (!config.field) return campaigns;
  const field = config.field;
  return [...campaigns].sort((a, b) => {
    const av = a[field] as number;
    const bv = b[field] as number;
    return config.dir === 'asc' ? av - bv : bv - av;
  });
}

// --- Component ---

export default function AdsPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) router.replace('/login');
  }, [router]);

  // Insight → action bridge: read ?focus=<campaign name> on mount.
  // useSearchParams is intentionally avoided (CSR-bailout build warning risk);
  // this mirrors the window.location.search pattern used on /integrations.
  const [focusQuery, setFocusQuery] = useState('');
  const [focusedCampaignId, setFocusedCampaignId] = useState<string | null>(null);
  const [campaignSearch, setCampaignSearch] = useState('');
  const focusedRowRef = useRef<HTMLTableRowElement | null>(null);

  useEffect(() => {
    const focus = new URLSearchParams(window.location.search).get('focus');
    if (focus) {
      setFocusQuery(focus);
      setCampaignSearch(focus);
    }
  }, []);

  // Filters & dates
  const defaults = getDefaultDates();
  const [dateFrom, setDateFrom] = useState(defaults.from);
  const [dateTo, setDateTo] = useState(defaults.to);
  const [appliedFrom, setAppliedFrom] = useState(defaults.from);
  const [appliedTo, setAppliedTo] = useState(defaults.to);

  // Track which preset is currently active (null = custom/no match)
  const [activePreset, setActivePreset] = useState<PresetKey | null>(
    () => detectPreset(defaults.from, defaults.to),
  );
  const [channelFilter, setChannelFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<CampaignStatus | ''>('');
  const [appliedChannel, setAppliedChannel] = useState('');
  const [appliedStatus, setAppliedStatus] = useState<CampaignStatus | ''>('');

  // Sort
  const [sortConfig, setSortConfig] = useState<SortConfig>({
    field: 'spend',
    dir: 'desc',
  });

  // Campaigns
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [campaignsLoading, setCampaignsLoading] = useState(true);
  const [campaignsError, setCampaignsError] = useState<string | null>(null);

  const fetchCampaigns = useCallback(
    async (from: string, to: string, channel: string, status: CampaignStatus | '') => {
      setCampaignsLoading(true);
      setCampaignsError(null);
      try {
        const data = await getCampaigns({
          date_from: from,
          date_to: to,
          channel: channel || undefined,
          status: status || undefined,
        });
        setCampaigns(data);
      } catch (err: unknown) {
        setCampaignsError(parseApiError(err));
      } finally {
        setCampaignsLoading(false);
      }
    },
    [],
  );

  // Recommendations
  const [recos, setRecos] = useState<Recommendation[]>([]);
  const [recosLoading, setRecosLoading] = useState(true);
  const [recosError, setRecosError] = useState<string | null>(null);

  const fetchRecos = useCallback(async (from: string, to: string) => {
    setRecosLoading(true);
    setRecosError(null);
    try {
      const data = await getRecommendations({ date_from: from, date_to: to });
      setRecos(data);
    } catch (err: unknown) {
      setRecosError(parseApiError(err));
    } finally {
      setRecosLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    if (!getToken()) return;
    fetchCampaigns(appliedFrom, appliedTo, appliedChannel, appliedStatus);
    fetchRecos(appliedFrom, appliedTo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function applyFilters() {
    setAppliedFrom(dateFrom);
    setAppliedTo(dateTo);
    setAppliedChannel(channelFilter);
    setAppliedStatus(statusFilter);
    setActivePreset(detectPreset(dateFrom, dateTo));
    fetchCampaigns(dateFrom, dateTo, channelFilter, statusFilter);
    fetchRecos(dateFrom, dateTo);
  }

  function handlePresetSelect(from: string, to: string) {
    // Apply immediately; preserve existing channel/status filter values
    setDateFrom(from);
    setDateTo(to);
    setAppliedFrom(from);
    setAppliedTo(to);
    setAppliedChannel(channelFilter);
    setAppliedStatus(statusFilter);
    setActivePreset(detectPreset(from, to));
    fetchCampaigns(from, to, channelFilter, statusFilter);
    fetchRecos(from, to);
  }

  // Expanded campaign detail
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detailMap, setDetailMap] = useState<Record<string, CampaignDetail>>({});
  const [detailLoadingMap, setDetailLoadingMap] = useState<Record<string, boolean>>({});
  const [detailErrorMap, setDetailErrorMap] = useState<Record<string, string | null>>({});

  async function toggleCampaign(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    if (detailMap[id]) return; // already fetched

    setDetailLoadingMap((m) => ({ ...m, [id]: true }));
    setDetailErrorMap((m) => ({ ...m, [id]: null }));
    try {
      const data = await getCampaignDetail(id, appliedFrom, appliedTo);
      setDetailMap((m) => ({ ...m, [id]: data }));
    } catch (err: unknown) {
      setDetailErrorMap((m) => ({
        ...m,
        [id]: parseApiError(err),
      }));
    } finally {
      setDetailLoadingMap((m) => ({ ...m, [id]: false }));
    }
  }

  // Sort toggle
  function toggleSort(field: CampaignSortField) {
    setSortConfig((prev) => {
      if (prev.field === field) {
        return { field, dir: prev.dir === 'desc' ? 'asc' : 'desc' };
      }
      return { field, dir: 'desc' };
    });
  }

  function sortIcon(field: CampaignSortField): React.ReactNode {
    if (sortConfig.field !== field) {
      return <i className={styles.sortIcon}>&#8597;</i>;
    }
    return (
      <i className={`${styles.sortIcon} ${styles.sortIconActive}`}>
        {sortConfig.dir === 'desc' ? '↓' : '↑'}
      </i>
    );
  }

  // Client-side name filter (seeded from ?focus= on mount, editable after)
  // runs before sort/focus so search + sort + highlight all compose cleanly.
  const searchedCampaigns = filterCampaignsByName(campaigns, campaignSearch);
  const sortedCampaigns = sortCampaigns(searchedCampaigns, sortConfig);

  // Re-apply the focus highlight/reorder against the currently visible
  // (searched + sorted) list so the matched campaign always surfaces first.
  const { campaigns: focusedCampaigns, matchedId } = applyFocus(
    sortedCampaigns,
    focusQuery,
  );

  useEffect(() => {
    if (matchedId !== focusedCampaignId) {
      setFocusedCampaignId(matchedId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matchedId]);

  // Scroll the focused row into view once it's rendered.
  useEffect(() => {
    if (focusedCampaignId && focusedRowRef.current) {
      focusedRowRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [focusedCampaignId, campaignsLoading]);

  // CSV export state
  const [csvLoading, setCsvLoading] = useState(false);
  const [csvError, setCsvError] = useState<string | null>(null);

  async function handleCsvExport() {
    setCsvLoading(true);
    setCsvError(null);
    try {
      await downloadCsv(
        '/api/v1/ads/campaigns/export',
        {
          date_from: appliedFrom,
          date_to: appliedTo,
          channel: appliedChannel,
          status: appliedStatus,
        },
        `kampanyalar-${appliedFrom}-${appliedTo}.csv`,
      );
    } catch (err: unknown) {
      setCsvError(parseApiError(err));
    } finally {
      setCsvLoading(false);
    }
  }

  // "Coming soon" modal
  const [showComingSoon, setShowComingSoon] = useState(false);
  const [comingSoonAction, setComingSoonAction] = useState('');

  function handleRecoAction(action: string) {
    setComingSoonAction(action);
    setShowComingSoon(true);
  }

  // Unique channels for filter dropdown (derived from fetched campaigns)
  const allChannels = Array.from(new Set(campaigns.map((c) => c.channel))).sort();

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Reklam Yönetimi</h1>
            <p className={styles.pageSubtitle}>
              Tüm kanallarınızdaki reklam kampanyalarını tek ekrandan takip edin ve yönetin.
            </p>
          </div>
        </div>

        {/* Campaign table section */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>
              Kampanyalar
              {campaigns.length > 0 ? ` (${campaigns.length})` : ''}
            </h2>
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
          </div>

          {/* Toolbar */}
          <div className={styles.toolbar}>
            {/* Quick presets — full-width row above date inputs */}
            <div className={styles.presetsRow}>
              <DateRangePresets
                onSelect={handlePresetSelect}
                activePreset={activePreset}
              />
            </div>

            {/* Campaign name search — client-side filter; seeded by ?focus= */}
            <div className={styles.presetsRow}>
              <div className={styles.filterGroup}>
                <label className={styles.filterLabel} htmlFor="ads-campaign-search">
                  Kampanya ara
                </label>
                <input
                  id="ads-campaign-search"
                  type="text"
                  className={styles.dateInput}
                  placeholder="Kampanya adına göre filtrele..."
                  value={campaignSearch}
                  onChange={(e) => setCampaignSearch(e.target.value)}
                />
              </div>
            </div>

            <div className={styles.dateGroup}>
              <label className={styles.dateLabel} htmlFor="ads-from">
                Başlangıç
              </label>
              <input
                id="ads-from"
                type="date"
                className={styles.dateInput}
                value={dateFrom}
                max={dateTo}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </div>
            <div className={styles.dateGroup}>
              <label className={styles.dateLabel} htmlFor="ads-to">
                Bitiş
              </label>
              <input
                id="ads-to"
                type="date"
                className={styles.dateInput}
                value={dateTo}
                min={dateFrom}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </div>
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Kanal</label>
              <select
                className={styles.filterSelect}
                value={channelFilter}
                onChange={(e) => setChannelFilter(e.target.value)}
              >
                <option value="">Tüm Kanallar</option>
                {allChannels.map((ch) => (
                  <option key={ch} value={ch}>
                    {ch}
                  </option>
                ))}
              </select>
            </div>
            <div className={styles.filterGroup}>
              <label className={styles.filterLabel}>Durum</label>
              <select
                className={styles.filterSelect}
                value={statusFilter}
                onChange={(e) =>
                  setStatusFilter(e.target.value as CampaignStatus | '')
                }
              >
                <option value="">Tüm Durumlar</option>
                <option value="active">Aktif</option>
                <option value="paused">Duraklatıldı</option>
                <option value="ended">Bitti</option>
                <option value="draft">Taslak</option>
              </select>
            </div>
            <button className={styles.applyBtn} onClick={applyFilters}>
              Uygula
            </button>
          </div>

          {campaignsLoading ? (
            <LoadingState message="Kampanyalar yükleniyor..." />
          ) : campaignsError ? (
            <ErrorState
              message={campaignsError}
              onRetry={() =>
                fetchCampaigns(appliedFrom, appliedTo, appliedChannel, appliedStatus)
              }
            />
          ) : focusedCampaigns.length === 0 ? (
            <EmptyState
              title="Kampanya bulunamadı"
              description="Bu filtreler için kampanya bulunamadı."
            />
          ) : (
            <ErrorBoundary label="Kampanya Tablosu">
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th className={styles.th}>Kampanya</th>
                    <th className={styles.th}>Kanal</th>
                    <th className={styles.th}>Durum</th>
                    <th
                      className={`${styles.th} ${styles.thRight} ${styles.thSortable} ${sortConfig.field === 'spend' ? styles.thActive : ''}`}
                      onClick={() => toggleSort('spend')}
                    >
                      Harcama {sortIcon('spend')}
                    </th>
                    <th
                      className={`${styles.th} ${styles.thRight} ${styles.thSortable} ${sortConfig.field === 'roas' ? styles.thActive : ''}`}
                      onClick={() => toggleSort('roas')}
                    >
                      ROAS {sortIcon('roas')}
                    </th>
                    <th
                      className={`${styles.th} ${styles.thRight} ${styles.thSortable} ${sortConfig.field === 'cpc' ? styles.thActive : ''}`}
                      onClick={() => toggleSort('cpc')}
                    >
                      CPC {sortIcon('cpc')}
                    </th>
                    <th
                      className={`${styles.th} ${styles.thRight} ${styles.thSortable} ${sortConfig.field === 'ctr' ? styles.thActive : ''}`}
                      onClick={() => toggleSort('ctr')}
                    >
                      CTR {sortIcon('ctr')}
                    </th>
                    <th
                      className={`${styles.th} ${styles.thRight} ${styles.thSortable} ${sortConfig.field === 'conversions' ? styles.thActive : ''}`}
                      onClick={() => toggleSort('conversions')}
                    >
                      Dönüşüm {sortIcon('conversions')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {focusedCampaigns.map((c, idx) => {
                    const isLast = idx === focusedCampaigns.length - 1;
                    const isExpanded = expandedId === c.campaign_id;
                    const isFocused = focusedCampaignId === c.campaign_id;
                    const detail = detailMap[c.campaign_id];
                    const detailLoading = detailLoadingMap[c.campaign_id] ?? false;
                    const detailError = detailErrorMap[c.campaign_id] ?? null;

                    return (
                      <>
                        <tr
                          key={c.campaign_id}
                          ref={isFocused ? focusedRowRef : undefined}
                          className={`${styles.campaignRow} ${isExpanded ? styles.campaignRowExpanded : ''} ${isLast && !isExpanded ? styles.campaignRowLast : ''} ${isFocused ? styles.rowFocused : ''}`}
                          onClick={() => toggleCampaign(c.campaign_id)}
                        >
                          <td className={styles.td}>
                            {c.campaign_name}
                          </td>
                          <td className={styles.td}>{channelLabel(c.channel)}</td>
                          <td className={styles.td}>
                            <span
                              className={`${styles.badge} ${statusBadgeClass(c.status)}`}
                            >
                              {statusLabel(c.status)}
                            </span>
                          </td>
                          <td className={`${styles.td} ${styles.tdRight}`}>
                            {fmtCurrency(c.spend)}
                          </td>
                          <td className={`${styles.td} ${styles.tdRight} ${roasClass(c.roas)}`}>
                            {fmtRoas(c.roas)}
                          </td>
                          <td className={`${styles.td} ${styles.tdRight}`}>
                            {fmtCurrency(c.cpc, 2)}
                          </td>
                          <td className={`${styles.td} ${styles.tdRight}`}>
                            {fmtPct(c.ctr)}
                          </td>
                          <td className={`${styles.td} ${styles.tdRight}`}>
                            {fmtNum(c.conversions)}
                          </td>
                        </tr>

                        {isExpanded && (
                          <tr key={`${c.campaign_id}-detail`} className={styles.expandedRow}>
                            <td colSpan={8}>
                              <div className={styles.expandedCell}>
                                <div className={styles.expandedTitle}>
                                  {c.campaign_name} — Zaman Serisi (Harcama)
                                </div>
                                <TimeSeriesChart
                                  points={detail?.timeseries ?? []}
                                  metricLabel="Harcama"
                                  loading={detailLoading}
                                  error={detailError}
                                />
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
            </ErrorBoundary>
          )}
        </section>

        {/* Recommendations section — grouped by campaign */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>
              Öneriler
              {recos.length > 0 ? ` (${recos.length})` : ''}
            </h2>
          </div>
          {recosLoading ? (
            <LoadingState message="Öneriler yükleniyor..." />
          ) : recosError ? (
            <ErrorState
              message={recosError}
              onRetry={() => fetchRecos(appliedFrom, appliedTo)}
            />
          ) : recos.length === 0 ? (
            <EmptyState
              title="Öneri bulunmuyor"
              description="Bu dönem için öneri bulunmuyor."
            />
          ) : (
            <ErrorBoundary label="Öneriler">
            <div className={styles.recoGrouped}>
              {groupRecos(recos).map((group) => (
                <div key={group.campaign_id} className={styles.recoGroup}>
                  <div className={styles.recoGroupHeader}>
                    {group.campaign_name}
                    <span className={styles.recoGroupCount}>{group.items.length}</span>
                  </div>
                  {group.items.map((r, idx) => (
                    <div key={`${r.campaign_id}-${idx}`} className={styles.recoRow}>
                      <div className={styles.recoBadgeCol}>
                        <span
                          className={`${styles.badge} ${recoSeverityClass(r.severity)}`}
                        >
                          {recoSeverityLabel(r.severity)}
                        </span>
                      </div>
                      <div className={styles.recoBody}>
                        <div className={styles.recoMessage}>{r.message}</div>
                        <div className={styles.recoAction}>{r.suggested_action}</div>
                      </div>
                      <button
                        className={styles.recoBtn}
                        onClick={() => handleRecoAction(r.suggested_action)}
                      >
                        {r.suggested_action} &rarr;
                      </button>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            </ErrorBoundary>
          )}
        </section>
      </main>

      {/* Coming soon modal */}
      {showComingSoon && (
        <div
          className={styles.comingSoonOverlay}
          onClick={() => setShowComingSoon(false)}
        >
          <div
            className={styles.comingSoonBox}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.comingSoonTitle}>Yakında</div>
            <p className={styles.comingSoonBody}>
              <strong>{comingSoonAction}</strong> özelliği M6 Faz 2 kapsamında
              hayata geçirilecektir. Otomatik kampanya aksiyonları şu an
              kullanılamıyor.
            </p>
            <button
              className={styles.comingSoonClose}
              onClick={() => setShowComingSoon(false)}
            >
              Anladım
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
