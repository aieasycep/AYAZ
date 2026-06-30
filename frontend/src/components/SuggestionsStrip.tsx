import Link from 'next/link';
import styles from './SuggestionsStrip.module.css';

export interface Suggestion {
  label: string;
  href: string;
}

interface SuggestionsStripProps {
  title?: string;
  suggestions: Suggestion[];
}

export default function SuggestionsStrip({
  title = 'Başlamak için',
  suggestions,
}: SuggestionsStripProps) {
  return (
    <section className={styles.strip} aria-label="Öneriler">
      {title && <div className={styles.title}>{title}</div>}
      <div className={styles.grid}>
        {suggestions.map((s) => (
          <Link key={s.href} href={s.href} className={styles.card}>
            {s.label}
            <span className={styles.arrow} aria-hidden="true">&rarr;</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
