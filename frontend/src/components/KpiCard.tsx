'use client';

import styles from './KpiCard.module.css';

interface KpiCardProps {
  label: string;
  value: string;
  sub?: string;
}

export default function KpiCard({ label, value, sub }: KpiCardProps) {
  return (
    <div className={styles.card}>
      <span className={styles.label}>{label}</span>
      <span className={styles.value}>{value}</span>
      {sub && <span className={styles.sub}>{sub}</span>}
    </div>
  );
}
