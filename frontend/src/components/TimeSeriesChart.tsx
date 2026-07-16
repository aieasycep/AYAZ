'use client';

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { TimeseriesPoint } from '@/lib/api';
import styles from './TimeSeriesChart.module.css';

interface TimeSeriesChartProps {
  points: TimeseriesPoint[];
  metricLabel: string;
  loading: boolean;
  error: string | null;
}

function formatValue(value: number, metricLabel: string): string {
  if (metricLabel === 'Harcama') {
    return new Intl.NumberFormat('tr-TR', {
      style: 'currency',
      currency: 'TRY',
      minimumFractionDigits: 0,
    }).format(value);
  }
  if (metricLabel === 'ROAS') {
    return value.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + 'x';
  }
  return new Intl.NumberFormat('tr-TR').format(Math.round(value));
}

export default function TimeSeriesChart({
  points,
  metricLabel,
  loading,
  error,
}: TimeSeriesChartProps) {
  if (loading) {
    return (
      <div className={styles.placeholder}>
        <span className={styles.muted}>Yükleniyor...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.placeholder}>
        <span className={styles.errorText}>{error}</span>
      </div>
    );
  }

  if (!points.length) {
    return (
      <div className={styles.placeholder}>
        <span className={styles.muted}>Bu dönem için veri bulunmuyor.</span>
      </div>
    );
  }

  const data = points.map((p) => ({
    date: p.date.slice(5), // MM-DD
    value: p.value,
  }));

  return (
    <div className={styles.chartWrap}>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e5ef" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: '#6b7280' }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#6b7280' }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => {
              if (v >= 1_000_000) return (v / 1_000_000).toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + 'M';
              if (v >= 1_000) return (v / 1_000).toFixed(0) + 'K';
              return String(v);
            }}
            width={56}
          />
          <Tooltip
            formatter={(value: number) => [
              formatValue(value, metricLabel),
              metricLabel,
            ]}
            labelFormatter={(label: string) => `Tarih: ${label}`}
            contentStyle={{
              borderRadius: 8,
              border: '1px solid #e2e5ef',
              fontSize: 13,
            }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#3b5bdb"
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
