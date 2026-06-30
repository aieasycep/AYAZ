'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { getConnectedAccounts } from '@/lib/connectors-api';
import { getGoals } from '@/lib/goals-api';
import { getAutomationRules } from '@/lib/automation-api';
import styles from './GettingStarted.module.css';

// ---- localStorage keys --------------------------------------------------------

const DISMISSED_KEY = 'ayaz_onboarding_dismissed';
const ASSISTANT_SEEN_KEY = 'ayaz_onboarding_assistant_seen';

// ---- Types --------------------------------------------------------------------

interface StepState {
  hasAccount: boolean;
  hasGoal: boolean;
  hasRule: boolean;
  hasAssistantSeen: boolean;
}

type LoadStatus = 'idle' | 'loading' | 'done' | 'all-failed';

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

export default function GettingStarted() {
  const [mounted, setMounted] = useState<boolean>(false);
  const [dismissed, setDismissed] = useState<boolean>(false);
  const [status, setStatus] = useState<LoadStatus>('idle');

  // Render nothing until mounted so the server HTML and the first client render
  // match (this card depends on localStorage, which is client-only).
  useEffect(() => {
    setMounted(true);
  }, []);
  const [steps, setSteps] = useState<StepState>({
    hasAccount: false,
    hasGoal: false,
    hasRule: false,
    hasAssistantSeen: false,
  });

  // Hydrate dismissed + assistant-seen from localStorage once on client
  useEffect(() => {
    if (readLocalBool(DISMISSED_KEY)) {
      setDismissed(true);
      return; // no point fetching if already dismissed
    }

    const assistantSeen = readLocalBool(ASSISTANT_SEEN_KEY);

    // Fetch the three API lists in parallel; treat each failure as "not done"
    setStatus('loading');

    Promise.allSettled([
      getConnectedAccounts(),
      getGoals(),
      getAutomationRules(),
    ]).then(([accountsResult, goalsResult, rulesResult]) => {
      const allFailed =
        accountsResult.status === 'rejected' &&
        goalsResult.status === 'rejected' &&
        rulesResult.status === 'rejected';

      if (allFailed) {
        setStatus('all-failed');
        return;
      }

      setSteps({
        hasAccount:
          accountsResult.status === 'fulfilled' &&
          accountsResult.value.length > 0,
        hasGoal:
          goalsResult.status === 'fulfilled' && goalsResult.value.length > 0,
        hasRule:
          rulesResult.status === 'fulfilled' && rulesResult.value.length > 0,
        hasAssistantSeen: assistantSeen,
      });
      setStatus('done');
    });
  }, []);

  // ---- Derived state ----------------------------------------------------------

  const doneCount =
    (steps.hasAccount ? 1 : 0) +
    (steps.hasGoal ? 1 : 0) +
    (steps.hasRule ? 1 : 0) +
    (steps.hasAssistantSeen ? 1 : 0);

  const allDone = doneCount === 4;

  // ---- Handlers ---------------------------------------------------------------

  function handleDismiss() {
    writeLocalBool(DISMISSED_KEY);
    setDismissed(true);
  }

  function handleAssistantClick() {
    writeLocalBool(ASSISTANT_SEEN_KEY);
    setSteps((prev) => ({ ...prev, hasAssistantSeen: true }));
  }

  // ---- Visibility guard -------------------------------------------------------

  // During SSR / before hydration, render nothing (matches server output).
  if (!mounted) return null;
  // Dismissed or all done — hide the card
  if (dismissed || allDone) return null;
  // All fetches failed — ancillary card; don't show broken UI
  if (status === 'all-failed') return null;

  // ---- Render -----------------------------------------------------------------

  const progressPct = Math.round((doneCount / 4) * 100);

  return (
    <section className={styles.card} aria-label="Başlangıç rehberi">
      {/* Header */}
      <div className={styles.header}>
        <h2 className={styles.title}>Başlangıc</h2>
        <button
          className={styles.dismissBtn}
          onClick={handleDismiss}
          aria-label="Başlangıç rehberini gizle"
          type="button"
        >
          &times;
        </button>
      </div>

      {/* Progress */}
      <div className={styles.progress}>
        <span className={styles.progressLabel}>
          {doneCount}/4 tamamlandı
        </span>
        <div className={styles.progressBar} role="progressbar" aria-valuenow={doneCount} aria-valuemin={0} aria-valuemax={4}>
          <div
            className={styles.progressFill}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Loading overlay on first fetch */}
      {status === 'loading' && (
        <div className={styles.loading} role="status" aria-live="polite">
          <span className={styles.loadingSpinner} aria-hidden="true" />
          Adımlar yükleniyor...
        </div>
      )}

      {/* Steps — shown even during load (all default to todo, which is safe) */}
      {status !== 'loading' && (
        <ol className={styles.steps}>
          {/* Step 1: Connect an account */}
          <li className={styles.step}>
            <span
              className={`${styles.indicator} ${steps.hasAccount ? styles.indicatorDone : styles.indicatorTodo}`}
              aria-hidden="true"
            >
              {steps.hasAccount ? '✓' : '1'}
            </span>
            <div className={styles.stepBody}>
              <span
                className={`${styles.stepTitle} ${steps.hasAccount ? styles.stepTitleDone : styles.stepTitleTodo}`}
              >
                Hesabını bağla
              </span>
              {!steps.hasAccount && (
                <Link href="/integrations?tab=veri-kaynaklari" className={styles.ctaLink}>
                  Reklam/analitik hesabını bağla &rarr;
                </Link>
              )}
            </div>
          </li>

          {/* Step 2: Set a goal */}
          <li className={styles.step}>
            <span
              className={`${styles.indicator} ${steps.hasGoal ? styles.indicatorDone : styles.indicatorTodo}`}
              aria-hidden="true"
            >
              {steps.hasGoal ? '✓' : '2'}
            </span>
            <div className={styles.stepBody}>
              <span
                className={`${styles.stepTitle} ${steps.hasGoal ? styles.stepTitleDone : styles.stepTitleTodo}`}
              >
                İlk hedefini koy
              </span>
              {!steps.hasGoal && (
                <Link href="/goals" className={styles.ctaLink}>
                  Hedef ekle &rarr;
                </Link>
              )}
            </div>
          </li>

          {/* Step 3: Create an automation rule */}
          <li className={styles.step}>
            <span
              className={`${styles.indicator} ${steps.hasRule ? styles.indicatorDone : styles.indicatorTodo}`}
              aria-hidden="true"
            >
              {steps.hasRule ? '✓' : '3'}
            </span>
            <div className={styles.stepBody}>
              <span
                className={`${styles.stepTitle} ${steps.hasRule ? styles.stepTitleDone : styles.stepTitleTodo}`}
              >
                Otomasyon kuralı oluştur
              </span>
              {!steps.hasRule && (
                <Link href="/automation" className={styles.ctaLink}>
                  Kural oluştur &rarr;
                </Link>
              )}
            </div>
          </li>

          {/* Step 4: Try AI Assistant (localStorage-only detection) */}
          <li className={styles.step}>
            <span
              className={`${styles.indicator} ${steps.hasAssistantSeen ? styles.indicatorDone : styles.indicatorTodo}`}
              aria-hidden="true"
            >
              {steps.hasAssistantSeen ? '✓' : '4'}
            </span>
            <div className={styles.stepBody}>
              <span
                className={`${styles.stepTitle} ${steps.hasAssistantSeen ? styles.stepTitleDone : styles.stepTitleTodo}`}
              >
                AI Asistan&apos;ı dene
              </span>
              {!steps.hasAssistantSeen && (
                <Link
                  href="/assistant"
                  className={styles.ctaLink}
                  onClick={handleAssistantClick}
                >
                  Asistanı aç &rarr;
                </Link>
              )}
            </div>
          </li>
        </ol>
      )}
    </section>
  );
}
