import type { ReactNode } from 'react';
import Link from 'next/link';
import styles from './EmptyState.module.css';

interface EmptyStateAction {
  label: string;
  onClick?: () => void;
  href?: string;
}

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  subtitle?: string;
  action?: EmptyStateAction;
}

function DefaultIcon() {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect
        x="8"
        y="14"
        width="32"
        height="24"
        rx="3"
        stroke="currentColor"
        strokeWidth="2"
        fill="none"
      />
      <path
        d="M16 14V11a2 2 0 012-2h12a2 2 0 012 2v3"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d="M24 26v-6M21 23h6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function EmptyState({ icon, title, subtitle, action }: EmptyStateProps) {
  return (
    <div className={styles.container}>
      <div className={styles.iconWrap}>
        {icon ?? <DefaultIcon />}
      </div>
      <p className={styles.title}>{title}</p>
      {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
      {action && (
        action.href ? (
          <Link href={action.href} className={styles.actionBtn}>
            {action.label}
          </Link>
        ) : (
          <button
            type="button"
            className={styles.actionBtn}
            onClick={action.onClick}
          >
            {action.label}
          </button>
        )
      )}
    </div>
  );
}
