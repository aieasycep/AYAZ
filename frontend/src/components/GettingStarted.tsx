'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  getOnboardingStatus,
  type OnboardingStatus,
} from '@/lib/onboarding-api';
import styles from './GettingStarted.module.css';

// ---- localStorage keys --------------------------------------------------------

const DISMISSED_KEY = 'ayaz_onboarding_dismissed';

// ---- Types --------------------------------------------------------------------

type LoadStatus = 'idle' | 'loading' | 'done' | 'failed';

// ---- Helpers ------------------------------------------------------------------

function readLocalBool(key: string): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(key) === '1';
}

function writeLocalBool(key: string): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(key, '1');
}

// ---- Component ----------------------------------------------------------------

// This dashboard card is the at-a-glance summary of the SAME setup checklist
// shown in full on /onboarding. Both read from the canonical backend source
// (GET /api/v1/onboarding/status via getOnboardingStatus), so the step list and
// the progress numbers shown here always match /onboarding exactly — no more
// "1/4 here, 4/5 there" contradiction.
export default function GettingStarted() {
  const [mounted, setMounted] = useState<boolean>(false);
  const [dismissed, setDismissed] = useState<boolean>(false);
  const [status, setStatus] = useState<LoadStatus>('idle');
  const [data, setData] = useState<OnboardingStatus | null>(null);

  // Render nothing until mounted so the server HTML and the first client render
  // match (this card depends on localStorage, which is client-only).
  useEffect(() => {
    setMounted(true);
  }, []);

  // Hydrate dismissed from localStorage, then fetch the canonical status once.
  useEffect(() => {
    if (readLocalBool(DISMISSED_KEY)) {
      setDismissed(true);
      return; // no point fetching if already dismissed
    }
    setStatus('loading');
    getOnboardingStatus()
      .then((result) => {
        setData(result);
        setStatus('done');
      })
      .catch(() => setStatus('failed'));
  }, []);

  // ---- Handlers ---------------------------------------------------------------

  function handleDismiss() {
    writeLocalBool(DISMISSED_KEY);
    setDismissed(true);
  }

  // ---- Visibility guard -------------------------------------------------------

  // During SSR / before hydration, render nothing (matches server output).
  if (!mounted) return null;
  // Dismissed — hide the card
  if (dismissed) return null;
  // Fetch failed — ancillary card, don't show broken UI
  if (status === 'failed') return null;
  // All done — hide (same all_done flag /onboarding uses)
  if (data?.all_done) return null;

  // ---- Render -----------------------------------------------------------------

  const clampedPct = data ? Math.min(Math.max(data.percent, 0), 100) : 0;

  return (
    <section className={styles.card} aria-label="Başlangıç rehberi">
      {/* Header */}
      <div className={styles.header}>
        <h2 className={styles.title}>Başlangıç</h2>
        <button
          className={styles.dismissBtn}
          onClick={handleDismiss}
          aria-label="Başlangıç rehberini gizle"
          type="button"
        >
          &times;
        </button>
      </div>

      {/* Progress — sourced 1:1 from the canonical onboarding status */}
      {data && (
        <div className={styles.progress}>
          <span className={styles.progressLabel}>
            {data.completed_steps}/{data.total_steps} tamamlandı
          </span>
          <div
            className={styles.progressBar}
            role="progressbar"
            aria-valuenow={data.completed_steps}
            aria-valuemin={0}
            aria-valuemax={data.total_steps}
          >
            <div
              className={styles.progressFill}
              style={{ width: `${clampedPct}%` }}
            />
          </div>
        </div>
      )}

      {/* Loading overlay on first fetch */}
      {status === 'loading' && (
        <div className={styles.loading} role="status" aria-live="polite">
          <span className={styles.loadingSpinner} aria-hidden="true" />
          Adımlar yükleniyor...
        </div>
      )}

      {/* Steps — same canonical list /onboarding renders */}
      {status === 'done' && data && (
        <ol className={styles.steps}>
          {data.steps.map((step, idx) => (
            <li className={styles.step} key={step.key}>
              <span
                className={`${styles.indicator} ${step.done ? styles.indicatorDone : styles.indicatorTodo}`}
                aria-hidden="true"
              >
                {step.done ? '✓' : idx + 1}
              </span>
              <div className={styles.stepBody}>
                <span
                  className={`${styles.stepTitle} ${step.done ? styles.stepTitleDone : styles.stepTitleTodo}`}
                >
                  {step.title}
                </span>
                {!step.done && (
                  <Link href={step.cta_link} className={styles.ctaLink}>
                    {step.cta_label} &rarr;
                  </Link>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
