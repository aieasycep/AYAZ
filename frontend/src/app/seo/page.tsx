'use client';

import { useState, useEffect, useCallback } from 'react';
import AppNav from '@/components/AppNav';
import KpiCard from '@/components/KpiCard';
import SectionCard from '@/components/SectionCard';
import EmptyState from '@/components/EmptyState';
import {
  getSeoOverview,
  getSeoOpportunities,
  runSeoAudit,
  getSeoBacklinks,
  getSeoKeywords,
  OPPORTUNITY_TYPE_LABELS,
  type SeoOverviewResponse,
  type SeoOpportunitiesResponse,
  type SeoOpportunity,
  type SeoOpportunityType,
  type SeoAuditResponse,
  type SeoBacklinksResponse,
  type SeoKeywordsResponse,
} from '@/lib/seo-api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './seo.module.css';

// ── Tab types ──────────────────────────────────────────────────────────────────

type Tab = 'overview' | 'opportunities' | 'audit' | 'dataforseo';

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Genel Bakış (GSC)' },
  { id: 'opportunities', label: 'Fırsatlar' },
  { id: 'audit', label: 'Site Denetimi' },
  { id: 'dataforseo', label: 'Backlinkler & Anahtar Kelimeler' },
];

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtNum(n: number): string {
  return n.toLocaleString('tr-TR');
}

function fmtCtr(ctr: number): string {
  return '%' + (ctr * 100).toLocaleString('tr-TR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

function fmtPos(pos: number): string {
  return pos.toLocaleString('tr-TR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
}

/** Convert percent delta (0–100-scale) to KpiCard fractional delta (0–1-scale). */
function pctToFraction(pct: number | null | undefined): number | null {
  if (pct == null) return null;
  return pct / 100;
}

// ── Gauge ring SVG for Lighthouse scores ──────────────────────────────────────

const GAUGE_R = 32;
const GAUGE_CIRC = 2 * Math.PI * GAUGE_R;

function gaugeArcClass(score: number | null, s: typeof styles): string {
  if (score === null) return '';
  if (score >= 90) return s.gaugeArcGood;
  if (score >= 50) return s.gaugeArcFair;
  return s.gaugeArcPoor;
}

interface GaugeCardProps {
  label: string;
  score: number | null;
}

function GaugeCard({ label, score }: GaugeCardProps) {
  const offset = score === null ? GAUGE_CIRC : GAUGE_CIRC * (1 - score / 100);
  const arcCls = gaugeArcClass(score, styles);

  return (
    <div className={styles.gaugeCard}>
      <div className={styles.gaugeRingWrap}>
        <svg className={styles.gaugeRingCircle} viewBox="0 0 80 80" aria-hidden="true">
          <circle className={styles.gaugeTrack} cx="40" cy="40" r={GAUGE_R} />
          {score !== null && (
            <circle
              className={arcCls}
              cx="40"
              cy="40"
              r={GAUGE_R}
              strokeDasharray={GAUGE_CIRC}
              strokeDashoffset={offset}
            />
          )}
        </svg>
        {score !== null ? (
          <span className={styles.gaugeScore}>{score}</span>
        ) : (
          <span className={styles.gaugeScoreNull}>—</span>
        )}
      </div>
      <span className={styles.gaugeLabel}>{label}</span>
    </div>
  );
}

// ── CWV card ──────────────────────────────────────────────────────────────────

interface CwvCardProps {
  label: string;
  value: number | null;
  unit: string;
  score: number | null;
}

function cwvColorClass(score: number | null, s: typeof styles): string {
  if (score === null) return '';
  if (score >= 90) return s.cwvGood;
  if (score >= 50) return s.cwvNeedsWork;
  return s.cwvPoor;
}

function CwvCard({ label, value, unit, score }: CwvCardProps) {
  const colorCls = cwvColorClass(score, styles);
  return (
    <div className={styles.cwvCard}>
      <span className={styles.cwvLabel}>{label}</span>
      <span className={`${styles.cwvValue} ${colorCls}`}>
        {value !== null && value !== undefined
          ? value.toLocaleString('tr-TR', { maximumFractionDigits: 3 })
          : '—'}
      </span>
      <span className={styles.cwvUnit}>{unit}</span>
    </div>
  );
}

// ── Opportunity card ──────────────────────────────────────────────────────────

function oppBadgeClass(severity: SeoOpportunity['severity'], s: typeof styles): string {
  switch (severity) {
    case 'critical': return s.oppBadgeCritical;
    case 'warning': return s.oppBadgeWarning;
    case 'info': return s.oppBadgeInfo;
  }
}

function oppDotClass(severity: SeoOpportunity['severity'], s: typeof styles): string {
  switch (severity) {
    case 'critical': return s.oppSeverityCritical;
    case 'warning': return s.oppSeverityWarning;
    case 'info': return s.oppSeverityInfo;
  }
}

const SEVERITY_LABELS_TR: Record<SeoOpportunity['severity'], string> = {
  critical: 'Kritik',
  warning: 'Uyarı',
  info: 'Bilgi',
};

function OpportunityCard({ opp }: { opp: SeoOpportunity }) {
  const data = opp.data as Record<string, unknown>;
  return (
    <div className={styles.oppCard}>
      <div className={styles.oppLeft}>
        <span className={`${styles.oppSeverityDot} ${oppDotClass(opp.severity, styles)}`} />
      </div>
      <div className={styles.oppBody}>
        <div className={styles.oppTitle}>{opp.title}</div>
        <div className={styles.oppText}>{opp.body}</div>
        <div className={styles.oppMeta}>
          {data.impressions !== undefined && (
            <span className={styles.oppMetaItem}>
              Gösterim: <span className={styles.oppMetaValue}>{fmtNum(Number(data.impressions))}</span>
            </span>
          )}
          {data.clicks !== undefined && (
            <span className={styles.oppMetaItem}>
              Tıklama: <span className={styles.oppMetaValue}>{fmtNum(Number(data.clicks))}</span>
            </span>
          )}
          {data.avg_position !== undefined && (
            <span className={styles.oppMetaItem}>
              Ort. Konum: <span className={styles.oppMetaValue}>{fmtPos(Number(data.avg_position))}</span>
            </span>
          )}
          {data.ctr !== undefined && (
            <span className={styles.oppMetaItem}>
              CTR: <span className={styles.oppMetaValue}>{fmtCtr(Number(data.ctr))}</span>
            </span>
          )}
          {data.page_count !== undefined && (
            <span className={styles.oppMetaItem}>
              Sayfa: <span className={styles.oppMetaValue}>{String(data.page_count)}</span>
            </span>
          )}
        </div>
      </div>
      <div>
        <span className={`${styles.oppBadge} ${oppBadgeClass(opp.severity, styles)}`}>
          {SEVERITY_LABELS_TR[opp.severity]}
        </span>
      </div>
    </div>
  );
}

// ── Loading skeletons ─────────────────────────────────────────────────────────

function OverviewSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonKpiRow}`} />
      <div className={`${styles.skeleton} ${styles.skeletonBlock}`} />
      <div className={`${styles.skeleton} ${styles.skeletonBlock}`} />
    </>
  );
}

function GenericSkeleton() {
  return <div className={`${styles.skeleton} ${styles.skeletonBlock}`} />;
}

// ── Tab: Genel Bakış ──────────────────────────────────────────────────────────

interface OverviewTabProps {
  periodDays: number;
}

function OverviewTab({ periodDays }: OverviewTabProps) {
  const [data, setData] = useState<SeoOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSeoOverview(periodDays);
      setData(res);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, [periodDays]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <OverviewSkeleton />;

  if (error) {
    return (
      <SectionCard>
        <div className={styles.errorBox}>
          <span className={styles.errorText}>{error}</span>
          <button type="button" className={styles.retryBtn} onClick={load}>
            Tekrar Dene
          </button>
        </div>
      </SectionCard>
    );
  }

  if (!data) return null;

  const { current, trends } = data;

  return (
    <>
      {/* KPI Cards */}
      <div className={styles.kpiGrid}>
        <KpiCard
          label="Tıklama"
          value={fmtNum(current.clicks)}
          delta={pctToFraction(trends.clicks_delta_pct)}
        />
        <KpiCard
          label="Gösterim"
          value={fmtNum(current.impressions)}
          delta={pctToFraction(trends.impressions_delta_pct)}
        />
        <KpiCard
          label="CTR"
          value={fmtCtr(current.ctr)}
          delta={pctToFraction(trends.ctr_delta_pct)}
        />
        <KpiCard
          label="Ort. Pozisyon"
          value={fmtPos(current.avg_position)}
          delta={pctToFraction(trends.position_delta_pct)}
          invertDelta
          sub="Düşük = daha iyi"
        />
      </div>

      {/* Top Queries table */}
      <SectionCard title="Top Sorgular">
        {data.top_queries.length === 0 ? (
          <p className={styles.emptyText}>GSC verisi henüz yok.</p>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Sorgu</th>
                  <th>Tıklama</th>
                  <th>Gösterim</th>
                  <th>CTR</th>
                  <th>Ort. Pozisyon</th>
                </tr>
              </thead>
              <tbody>
                {data.top_queries.map((q) => (
                  <tr key={q.query}>
                    <td className={styles.tableDimension}>{q.query}</td>
                    <td className={styles.tableNum}>{fmtNum(q.clicks)}</td>
                    <td className={styles.tableNum}>{fmtNum(q.impressions)}</td>
                    <td className={styles.tableNumMuted}>{fmtCtr(q.ctr)}</td>
                    <td className={styles.tableNumMuted}>{fmtPos(q.avg_position)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {/* Top Pages table */}
      <SectionCard title="Top Sayfalar">
        {data.top_pages.length === 0 ? (
          <p className={styles.emptyText}>GSC verisi henüz yok.</p>
        ) : (
          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Sayfa</th>
                  <th>Tıklama</th>
                  <th>Gösterim</th>
                  <th>CTR</th>
                  <th>Ort. Pozisyon</th>
                </tr>
              </thead>
              <tbody>
                {data.top_pages.map((p) => (
                  <tr key={p.page}>
                    <td className={styles.tableDimension}>
                      <a
                        href={p.page}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.tableDimensionLink}
                        title={p.page}
                      >
                        {p.page}
                      </a>
                    </td>
                    <td className={styles.tableNum}>{fmtNum(p.clicks)}</td>
                    <td className={styles.tableNum}>{fmtNum(p.impressions)}</td>
                    <td className={styles.tableNumMuted}>{fmtCtr(p.ctr)}</td>
                    <td className={styles.tableNumMuted}>{fmtPos(p.avg_position)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
    </>
  );
}

// ── Tab: Fırsatlar ────────────────────────────────────────────────────────────

const OPP_TYPE_ORDER: SeoOpportunityType[] = [
  'striking_distance',
  'low_ctr',
  'cannibalization',
  'top_movers',
];

interface OpportunitiesTabProps {
  periodDays: number;
}

function OpportunitiesTab({ periodDays }: OpportunitiesTabProps) {
  const [data, setData] = useState<SeoOpportunitiesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getSeoOpportunities(periodDays);
      setData(res);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, [periodDays]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <GenericSkeleton />;

  if (error) {
    return (
      <SectionCard>
        <div className={styles.errorBox}>
          <span className={styles.errorText}>{error}</span>
          <button type="button" className={styles.retryBtn} onClick={load}>
            Tekrar Dene
          </button>
        </div>
      </SectionCard>
    );
  }

  if (!data || data.opportunities.length === 0) {
    return (
      <EmptyState
        title="Fırsat bulunamadı"
        subtitle="Seçilen dönemde analiz için yeterli GSC verisi yok."
      />
    );
  }

  // Group by type in defined order
  const grouped: Record<SeoOpportunityType, SeoOpportunity[]> = {
    striking_distance: [],
    low_ctr: [],
    cannibalization: [],
    top_movers: [],
  };
  for (const opp of data.opportunities) {
    if (grouped[opp.type]) {
      grouped[opp.type].push(opp);
    }
  }

  return (
    <div className={styles.oppSection}>
      {OPP_TYPE_ORDER.map((type) => {
        const items = grouped[type];
        if (items.length === 0) return null;
        return (
          <div key={type}>
            <div className={styles.oppGroupLabel}>{OPPORTUNITY_TYPE_LABELS[type]}</div>
            <div className={styles.oppSection}>
              {items.map((opp, idx) => (
                <OpportunityCard key={`${type}-${idx}`} opp={opp} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Tab: Site Denetimi ────────────────────────────────────────────────────────

function AuditTab() {
  const [url, setUrl] = useState('');
  const [strategy, setStrategy] = useState<'mobile' | 'desktop'>('mobile');
  const [result, setResult] = useState<SeoAuditResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAudit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await runSeoAudit(url.trim(), strategy);
      setResult(res);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }

  const cwv = result?.core_web_vitals;
  const lh = result?.lighthouse_scores;

  return (
    <>
      <SectionCard title="Site URL'si Denetle">
        <form className={styles.auditForm} onSubmit={handleAudit}>
          <div className={styles.auditInputGroup}>
            <label className={styles.auditLabel} htmlFor="audit-url">
              URL
            </label>
            <input
              id="audit-url"
              type="url"
              className={styles.auditInput}
              placeholder="https://example.com/"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              required
            />
          </div>
          <div className={styles.strategyToggle}>
            <button
              type="button"
              className={`${styles.strategyBtn} ${strategy === 'mobile' ? styles.strategyBtnActive : ''}`}
              onClick={() => setStrategy('mobile')}
            >
              Mobil
            </button>
            <button
              type="button"
              className={`${styles.strategyBtn} ${strategy === 'desktop' ? styles.strategyBtnActive : ''}`}
              onClick={() => setStrategy('desktop')}
            >
              Masaüstü
            </button>
          </div>
          <button type="submit" className={styles.auditBtn} disabled={loading || !url.trim()}>
            {loading ? 'Denetleniyor…' : 'Denetle'}
          </button>
        </form>
      </SectionCard>

      {error && (
        <SectionCard>
          <div className={styles.errorBox}>
            <span className={styles.errorText}>{error}</span>
          </div>
        </SectionCard>
      )}

      {result && (result.status === 'kimlik_bekliyor' || result.status === 'error') && (
        <EmptyState
          title={
            result.status === 'kimlik_bekliyor'
              ? 'PageSpeed API kimlik bilgileri eksik'
              : 'Denetim tamamlanamadı'
          }
          subtitle={result.message ?? 'Lütfen daha sonra tekrar deneyin.'}
        />
      )}

      {result && result.status === 'ok' && (
        <div className={styles.auditResults}>
          {/* Core Web Vitals */}
          {cwv && (
            <SectionCard title="Core Web Vitals">
              <div className={styles.cwvGrid}>
                <CwvCard
                  label="LCP"
                  value={cwv.lcp.value}
                  unit={cwv.lcp.unit || 's'}
                  score={cwv.lcp.score}
                />
                <CwvCard
                  label="CLS"
                  value={cwv.cls.value}
                  unit={cwv.cls.unit || ''}
                  score={cwv.cls.score}
                />
                <CwvCard
                  label="FCP"
                  value={cwv.fcp.value}
                  unit={cwv.fcp.unit || 's'}
                  score={cwv.fcp.score}
                />
                <CwvCard
                  label="TTFB"
                  value={cwv.ttfb.value}
                  unit={cwv.ttfb.unit || 's'}
                  score={cwv.ttfb.score}
                />
              </div>
            </SectionCard>
          )}

          {/* Lighthouse scores */}
          {lh && (
            <SectionCard title="Lighthouse Puanları">
              <div className={styles.lighthouseGrid}>
                <GaugeCard label="Performans" score={lh.performance} />
                <GaugeCard label="SEO" score={lh.seo} />
                <GaugeCard label="Erişilebilirlik" score={lh.accessibility} />
                <GaugeCard label="En İyi Uygulamalar" score={lh.best_practices} />
              </div>
            </SectionCard>
          )}

          {/* Issues */}
          {result.issues && result.issues.length > 0 && (
            <SectionCard title="Tespit Edilen Sorunlar">
              <div className={styles.issueList}>
                {result.issues.map((issue) => {
                  const s = issue.score ?? null;
                  const scoreCls =
                    s === null
                      ? styles.issueScoreFair
                      : s >= 90
                      ? styles.issueScoreGood
                      : s >= 50
                      ? styles.issueScoreFair
                      : styles.issueScorePoor;

                  return (
                    <div key={issue.id} className={styles.issueRow}>
                      <div className={`${styles.issueScore} ${scoreCls}`}>
                        {s !== null ? Math.round(s) : '?'}
                      </div>
                      <div className={styles.issueBody}>
                        <div className={styles.issueTitle}>{issue.title}</div>
                        {issue.description && (
                          <div className={styles.issueDescription}>{issue.description}</div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </SectionCard>
          )}
        </div>
      )}
    </>
  );
}

// ── Tab: DataForSEO ───────────────────────────────────────────────────────────

function DataForSEOTab() {
  const [domain, setDomain] = useState('');
  const [seed, setSeed] = useState('');
  const [backlinks, setBacklinks] = useState<SeoBacklinksResponse | null>(null);
  const [keywords, setKeywords] = useState<SeoKeywordsResponse | null>(null);
  const [loadingBl, setLoadingBl] = useState(false);
  const [loadingKw, setLoadingKw] = useState(false);
  const [errorBl, setErrorBl] = useState<string | null>(null);
  const [errorKw, setErrorKw] = useState<string | null>(null);
  // Check connection status eagerly with a blank domain call
  const [connectRequired, setConnectRequired] = useState<boolean | null>(null);

  useEffect(() => {
    getSeoBacklinks('')
      .then((res) => {
        setConnectRequired(res.status === 'connect_required');
      })
      .catch(() => {
        setConnectRequired(false);
      });
  }, []);

  async function handleBacklinks(e: React.FormEvent) {
    e.preventDefault();
    if (!domain.trim()) return;
    setLoadingBl(true);
    setErrorBl(null);
    setBacklinks(null);
    try {
      const res = await getSeoBacklinks(domain.trim());
      setBacklinks(res);
    } catch (err: unknown) {
      setErrorBl(parseApiError(err));
    } finally {
      setLoadingBl(false);
    }
  }

  async function handleKeywords(e: React.FormEvent) {
    e.preventDefault();
    if (!seed.trim()) return;
    setLoadingKw(true);
    setErrorKw(null);
    setKeywords(null);
    try {
      const res = await getSeoKeywords(seed.trim());
      setKeywords(res);
    } catch (err: unknown) {
      setErrorKw(parseApiError(err));
    } finally {
      setLoadingKw(false);
    }
  }

  // Show connect gate immediately when we know connection is required
  if (connectRequired === true) {
    return (
      <EmptyState
        title="DataForSEO'yu bağlayın"
        subtitle="Backlink ve anahtar kelime verisi için DataForSEO entegrasyonunu etkinleştirmeniz gerekiyor."
        action={{ label: 'Entegrasyonlara Git', href: '/integrations' }}
      />
    );
  }

  // Show gate if a request returns connect_required
  if (
    (backlinks && backlinks.status === 'connect_required') ||
    (keywords && keywords.status === 'connect_required')
  ) {
    return (
      <EmptyState
        title="DataForSEO'yu bağlayın"
        subtitle="Backlink ve anahtar kelime verisi için DataForSEO entegrasyonunu etkinleştirmeniz gerekiyor."
        action={{ label: 'Entegrasyonlara Git', href: '/integrations' }}
      />
    );
  }

  return (
    <>
      {/* Backlinkler */}
      <SectionCard title="Backlink Analizi">
        <form className={styles.dfsSearchForm} onSubmit={handleBacklinks}>
          <input
            type="text"
            className={styles.dfsInput}
            placeholder="example.com"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            aria-label="Domain adı"
          />
          <button type="submit" className={styles.dfsBtn} disabled={loadingBl || !domain.trim()}>
            {loadingBl ? 'Yükleniyor…' : 'Analiz Et'}
          </button>
        </form>
        {errorBl && (
          <div className={styles.errorBox}>
            <span className={styles.errorText}>{errorBl}</span>
          </div>
        )}
        {backlinks && backlinks.status === 'ok' && 'total_backlinks' in backlinks && (
          <div className={styles.kpiGrid} style={{ marginTop: 'var(--space-4)' }}>
            <KpiCard label="Toplam Backlink" value={fmtNum((backlinks as { total_backlinks: number }).total_backlinks)} />
            <KpiCard label="Yönlendiren Domain" value={fmtNum((backlinks as { referring_domains: number }).referring_domains)} />
          </div>
        )}
        {backlinks && backlinks.status === 'error' && (
          <div className={styles.errorBox}>
            <span className={styles.errorText}>
              {'message' in backlinks ? String(backlinks.message) : 'Backlink verisi alınamadı.'}
            </span>
          </div>
        )}
      </SectionCard>

      {/* Anahtar Kelimeler */}
      <SectionCard title="Anahtar Kelime Fikirleri">
        <form className={styles.dfsSearchForm} onSubmit={handleKeywords}>
          <input
            type="text"
            className={styles.dfsInput}
            placeholder="Anahtar kelime girin…"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            aria-label="Anahtar kelime"
          />
          <button type="submit" className={styles.dfsBtn} disabled={loadingKw || !seed.trim()}>
            {loadingKw ? 'Yükleniyor…' : 'Ara'}
          </button>
        </form>
        {errorKw && (
          <div className={styles.errorBox}>
            <span className={styles.errorText}>{errorKw}</span>
          </div>
        )}
        {keywords && keywords.status === 'ok' && 'items' in keywords && (
          <div className={styles.tableWrapper} style={{ marginTop: 'var(--space-4)' }}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Anahtar Kelime</th>
                  <th>Aylık Arama</th>
                  <th>Zorluk</th>
                </tr>
              </thead>
              <tbody>
                {(keywords as { items: Array<{ keyword: string; volume: number; difficulty: number }> }).items.map((kw) => (
                  <tr key={kw.keyword}>
                    <td className={styles.tableDimension}>{kw.keyword}</td>
                    <td className={styles.tableNum}>{fmtNum(kw.volume)}</td>
                    <td className={styles.tableNumMuted}>{kw.difficulty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {keywords && keywords.status === 'error' && (
          <div className={styles.errorBox}>
            <span className={styles.errorText}>
              {'message' in keywords ? String(keywords.message) : 'Anahtar kelime verisi alınamadı.'}
            </span>
          </div>
        )}
      </SectionCard>
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SeoPage() {
  const [activeTab, setActiveTab] = useState<Tab>('overview');
  const [periodDays, setPeriodDays] = useState(30);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>SEO Paneli</h1>
            <p className={styles.pageSubtitle}>
              Google Search Console verileri, fırsat analizi, site denetimi ve
              DataForSEO backlink/kelime araştırması tek ekranda.
            </p>
          </div>
          {(activeTab === 'overview' || activeTab === 'opportunities') && (
            <select
              className={styles.periodSelect}
              value={periodDays}
              onChange={(e) => setPeriodDays(Number(e.target.value))}
              aria-label="Dönem seçin"
            >
              <option value={7}>Son 7 gün</option>
              <option value={14}>Son 14 gün</option>
              <option value={30}>Son 30 gün</option>
              <option value={60}>Son 60 gün</option>
              <option value={90}>Son 90 gün</option>
            </select>
          )}
        </div>

        {/* Tab strip */}
        <div className={styles.tabStrip} role="tablist" aria-label="SEO sekmeleri">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              className={`${styles.tabBtn} ${activeTab === tab.id ? styles.tabBtnActive : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        {activeTab === 'overview' && <OverviewTab periodDays={periodDays} />}
        {activeTab === 'opportunities' && <OpportunitiesTab periodDays={periodDays} />}
        {activeTab === 'audit' && <AuditTab />}
        {activeTab === 'dataforseo' && <DataForSEOTab />}
      </main>
    </div>
  );
}
