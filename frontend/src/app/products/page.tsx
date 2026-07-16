'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import PrintButton from '@/components/PrintButton';
import ReportPrintHeader from '@/components/ReportPrintHeader';
import { downloadRowsAsCsv } from '@/lib/csv';
import {
  getProductSegments,
  type ProductSegments,
  type ProductRow,
  type CategoryRow,
} from '@/lib/segments-api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './products.module.css';

// --- Formatters ---

function fmtTRY(n: number, decimals = 0): string {
  return new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: 'TRY',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function fmtRoas(n: number): string {
  return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + 'x';
}

function fmtPct(n: number): string {
  return '%' + n.toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function fmtInt(n: number): string {
  return n.toLocaleString('tr-TR', { maximumFractionDigits: 0 });
}

// --- Return-drag insight (the biggest gross→net ROAS gap) ---

function biggestReturnDrag(products: ProductRow[]): ProductRow | null {
  const withSpend = products.filter((p) => p.ad_spend > 0 && p.gross_roas > 0);
  if (withSpend.length === 0) return null;
  let worst = withSpend[0];
  for (const p of withSpend) {
    if (p.gross_roas - p.net_roas > worst.gross_roas - worst.net_roas) worst = p;
  }
  return worst.gross_roas - worst.net_roas >= 0.3 ? worst : null;
}

// High return rate → visually flag the row.
function returnRateClass(pct: number): string {
  if (pct >= 25) return styles.returnBad;
  if (pct >= 15) return styles.returnWarn;
  return '';
}

function netRoasClass(gross: number, net: number): string {
  if (gross <= 0) return '';
  if (net < 1) return styles.roasBad;
  if (net < gross * 0.7) return styles.roasWarn;
  return styles.roasGood;
}

// --- KPI card ---

function KpiCard({ label, value, highlight, hint }: { label: string; value: string; highlight?: boolean; hint?: string }) {
  return (
    <div className={styles.kpiCard}>
      <div className={styles.kpiLabel}>{label}</div>
      <div className={highlight ? styles.kpiValueHighlight : styles.kpiValue}>{value}</div>
      {hint && <div className={styles.kpiHint}>{hint}</div>}
    </div>
  );
}

// --- Loading skeleton ---

function LoadingSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonBanner}`} />
      <div className={styles.kpiGrid}>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={`${styles.skeleton} ${styles.skeletonCard}`} />
        ))}
      </div>
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// --- Category table ---

function CategoryTable({ rows }: { rows: CategoryRow[] }) {
  if (rows.length === 0) {
    return <div className={styles.stateBox}><span className={styles.muted}>Kategori verisi yok.</span></div>;
  }
  return (
    <div className={`${styles.tableWrap} table-scroll-hint`}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Kategori</th>
            <th className={styles.num}>Ürün</th>
            <th className={styles.num}>Net Ciro</th>
            <th className={styles.num}>Reklam</th>
            <th className={styles.num}>Brüt ROAS</th>
            <th className={styles.num}>Net ROAS</th>
            <th className={styles.num}>İade %</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.category}>
              <td className={styles.strong}>{c.category}</td>
              <td className={styles.num}>{fmtInt(c.product_count)}</td>
              <td className={styles.num}>{fmtTRY(c.net_revenue)}</td>
              <td className={styles.num}>{fmtTRY(c.ad_spend)}</td>
              <td className={styles.num}>{fmtRoas(c.gross_roas)}</td>
              <td className={`${styles.num} ${netRoasClass(c.gross_roas, c.net_roas)}`}>{fmtRoas(c.net_roas)}</td>
              <td className={`${styles.num} ${returnRateClass(c.return_rate_pct)}`}>{fmtPct(c.return_rate_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Product table ---

function ProductTable({ rows }: { rows: ProductRow[] }) {
  if (rows.length === 0) {
    return <div className={styles.stateBox}><span className={styles.muted}>Ürün verisi bulunamadı.</span></div>;
  }
  return (
    <div className={`${styles.tableWrap} table-scroll-hint`}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Ürün (SKU)</th>
            <th>Kategori</th>
            <th className={styles.num}>Adet</th>
            <th className={styles.num}>Net Ciro</th>
            <th className={styles.num}>Reklam</th>
            <th className={styles.num}>Brüt ROAS</th>
            <th className={styles.num}>Net ROAS</th>
            <th className={styles.num}>İade %</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.product_id}>
              <td>
                <div className={styles.strong}>{p.name}</div>
                <div className={styles.skuMeta}>{p.sku}</div>
              </td>
              <td>{p.category}</td>
              <td className={styles.num}>{fmtInt(p.units_sold)}</td>
              <td className={styles.num}>{fmtTRY(p.net_revenue)}</td>
              <td className={styles.num}>{fmtTRY(p.ad_spend)}</td>
              <td className={styles.num}>{fmtRoas(p.gross_roas)}</td>
              <td className={`${styles.num} ${netRoasClass(p.gross_roas, p.net_roas)}`}>{fmtRoas(p.net_roas)}</td>
              <td className={`${styles.num} ${returnRateClass(p.return_rate_pct)}`}>{fmtPct(p.return_rate_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- Main page ---

export default function ProductsPage() {
  const router = useRouter();
  useEffect(() => {
    if (!getToken()) router.replace('/login');
  }, [router]);

  const [data, setData] = useState<ProductSegments | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getProductSegments();
      setData(result);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchData();
  }, [fetchData]);

  const noData = data !== null && data.products.length === 0;
  const drag = data ? biggestReturnDrag(data.products) : null;

  function exportProducts() {
    if (!data) return;
    downloadRowsAsCsv(
      data.products.map((p) => ({
        sku: p.sku,
        urun: p.name,
        kategori: p.category,
        adet: p.units_sold,
        iade_adet: p.returned_units,
        brut_ciro: p.gross_revenue,
        net_ciro: p.net_revenue,
        reklam: p.ad_spend,
        brut_roas: p.gross_roas,
        net_roas: p.net_roas,
        iade_yuzde: p.return_rate_pct,
      })),
      `urun-segment-${data.period.date_from}-${data.period.date_to}.csv`,
      [
        { key: 'sku', label: 'SKU' },
        { key: 'urun', label: 'Ürün' },
        { key: 'kategori', label: 'Kategori' },
        { key: 'adet', label: 'Satılan Adet' },
        { key: 'iade_adet', label: 'İade Adet' },
        { key: 'brut_ciro', label: 'Brüt Ciro' },
        { key: 'net_ciro', label: 'Net Ciro' },
        { key: 'reklam', label: 'Reklam Harcaması' },
        { key: 'brut_roas', label: 'Brüt ROAS' },
        { key: 'net_roas', label: 'Net ROAS' },
        { key: 'iade_yuzde', label: 'İade %' },
      ],
    );
  }

  return (
    <div className={styles.shell}>
      <AppNav />
      <main className={styles.main}>
        {/* Header */}
        <div className={`${styles.pageHeader} print-hide`}>
          <div>
            <h1 className={styles.pageTitle}>Ürün Performansı</h1>
            <p className={styles.pageSubtitle}>
              SKU ve kategori bazında brüt ve iade-düzeltilmiş (net) ROAS — reklamdan
              en çok kazandıran ürünleri ve iadelerin gizli maliyetini görün.
            </p>
          </div>
          {data && !noData && (
            <div className={styles.headerActions}>
              <PrintButton className={styles.actionBtn} />
              <button className={styles.actionBtn} onClick={exportProducts}>CSV İndir</button>
            </div>
          )}
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <SectionCard>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchData}>Tekrar Dene</button>
            </div>
          </SectionCard>
        ) : data && noData ? (
          <SectionCard>
            <div className={styles.stateBox}>
              <span className={styles.muted}>
                Bu dönemde ürün satış verisi bulunamadı. Ürün/SKU verisi bağlandığında
                bu ekran otomatik dolar.
              </span>
            </div>
          </SectionCard>
        ) : data ? (
          <>
            {/* Branded print header */}
            <ReportPrintHeader
              title="Ürün Performansı"
              subtitle={`${data.period.date_from} — ${data.period.date_to}`}
            />

            {/* Return-drag insight */}
            {drag && (
              <div className={styles.insightBanner}>
                <span className={styles.insightIcon} aria-hidden="true">!</span>
                <p className={styles.insightText}>
                  <strong>İade uyarısı:</strong> {drag.name} brüt ROAS {fmtRoas(drag.gross_roas)} görünüyor
                  ama iadeler sonrası net ROAS {fmtRoas(drag.net_roas)}&apos;e düşüyor (%{drag.return_rate_pct.toLocaleString('tr-TR', { maximumFractionDigits: 1 })} iade).
                  Bu SKU&apos;da iade nedenlerini (beden/kalıp, ürün görseli, kalite) inceleyin.
                </p>
              </div>
            )}

            {/* KPI cards */}
            <div className={styles.kpiGrid}>
              <KpiCard label="Net Ciro" value={fmtTRY(data.totals.net_revenue)} hint={`Brüt ${fmtTRY(data.totals.gross_revenue)}`} />
              <KpiCard label="Net ROAS" value={fmtRoas(data.totals.net_roas)} highlight hint={`Brüt ${fmtRoas(data.totals.gross_roas)}`} />
              <KpiCard label="İade Oranı" value={fmtPct(data.totals.return_rate_pct)} hint={`${fmtInt(data.totals.returned_units)} iade`} />
              <KpiCard label="Reklam Harcaması" value={fmtTRY(data.totals.ad_spend)} hint={`${fmtInt(data.totals.product_count)} ürün`} />
            </div>

            {/* Category rollup */}
            <SectionCard
              title="Kategori Kırılımı"
              right={<span className={styles.periodLabel}>{data.period.date_from} — {data.period.date_to}</span>}
            >
              <CategoryTable rows={data.categories} />
            </SectionCard>

            {/* Per-SKU table */}
            <SectionCard title="SKU Detayı (reklam harcamasına göre)">
              <ProductTable rows={data.products} />
            </SectionCard>
          </>
        ) : null}
      </main>
    </div>
  );
}
