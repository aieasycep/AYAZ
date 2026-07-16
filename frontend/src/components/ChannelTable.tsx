'use client';

import type { ChannelRow } from '@/lib/api';
import { channelLabel } from '@/lib/channels';
import styles from './ChannelTable.module.css';

interface ChannelTableProps {
  rows: ChannelRow[];
  loading: boolean;
  error: string | null;
}

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
  return '%' + (n * 100).toLocaleString('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtRoas(n: number): string {
  return n.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + 'x';
}

export default function ChannelTable({ rows, loading, error }: ChannelTableProps) {
  if (loading) {
    return (
      <div className={styles.state}>
        <span className={styles.muted}>Yükleniyor...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.state}>
        <span className={styles.errorText}>{error}</span>
      </div>
    );
  }

  if (!rows.length) {
    return (
      <div className={styles.state}>
        <span className={styles.muted}>Bu dönem için kanal verisi bulunmuyor.</span>
      </div>
    );
  }

  return (
    <div className={`${styles.wrap} table-scroll-hint`}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.th}>Kanal</th>
            <th className={`${styles.th} ${styles.right}`}>Harcama</th>
            <th className={`${styles.th} ${styles.right}`}>Gösterim</th>
            <th className={`${styles.th} ${styles.right}`}>Tıklama</th>
            <th className={`${styles.th} ${styles.right}`}>Dönüşüm</th>
            <th className={`${styles.th} ${styles.right}`}>ROAS</th>
            <th className={`${styles.th} ${styles.right}`}>CPC</th>
            <th className={`${styles.th} ${styles.right}`}>CTR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.channel ?? i} className={styles.row}>
              <td className={`${styles.td} ${styles.channelCell}`}>{channelLabel(row.channel)}</td>
              <td className={`${styles.td} ${styles.right}`}>{fmtCurrency(row.spend)}</td>
              <td className={`${styles.td} ${styles.right}`}>{fmtNum(row.impressions)}</td>
              <td className={`${styles.td} ${styles.right}`}>{fmtNum(row.clicks)}</td>
              <td className={`${styles.td} ${styles.right}`}>{fmtNum(row.conversions)}</td>
              <td className={`${styles.td} ${styles.right}`}>
                {/* ₺0 harcamalı kanallarda (ör. GA4 gibi analitik kaynaklar) ROAS
                    matematiksel olarak tanımsızdır — "0.00x" göstermek yanıltıcı
                    olur (harcama olmadığı için verim değil "veri yok" durumudur). */}
                {row.spend === 0 ? (
                  <span
                    className={styles.muted}
                    title="Harcaması olmayan kaynaklarda ROAS anlamsızdır"
                  >
                    —
                  </span>
                ) : (
                  fmtRoas(row.roas)
                )}
              </td>
              <td className={`${styles.td} ${styles.right}`}>{fmtCurrency(row.cpc, 2)}</td>
              <td className={`${styles.td} ${styles.right}`}>{fmtPct(row.ctr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
