import type { ReactNode } from 'react';
import styles from './SectionCard.module.css';

interface SectionCardProps {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}

export default function SectionCard({ title, right, children, className }: SectionCardProps) {
  const hasHeader = title !== undefined || right !== undefined;
  return (
    <div className={`${styles.card} ${className ?? ''}`}>
      {hasHeader && (
        <div className={styles.header}>
          {title && <span className={styles.title}>{title}</span>}
          {right && <div className={styles.right}>{right}</div>}
        </div>
      )}
      <div className={styles.body}>{children}</div>
    </div>
  );
}
