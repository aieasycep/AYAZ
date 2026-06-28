'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import AppNav from '@/components/AppNav';
import {
  getOnboardingStatus,
  type OnboardingStatus,
  type OnboardingStep,
} from '@/lib/onboarding-api';
import styles from './onboarding.module.css';

// --- Helpers ---

function encouragingLine(percent: number): string {
  if (percent === 0) return 'Hadi başlayalım! İlk adımı tamamlayın.';
  if (percent < 40) return 'İyi bir başlangıç yaptınız, devam edin!';
  if (percent < 70) return 'Yarıya yaklaştınız, çok az kaldı!';
  if (percent < 100) return 'Neredeyse bitti, son adımları tamamlayın!';
  return 'Harika! Her şey hazır.';
}

// Returns the index of the first pending (not-done) step, or -1 if all done.
function firstPendingIndex(steps: OnboardingStep[]): number {
  return steps.findIndex((s) => !s.done);
}

// --- Loading skeleton ---

function LoadingSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonHero}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// --- Progress hero ---

interface ProgressHeroProps {
  data: OnboardingStatus;
}

function ProgressHero({ data }: ProgressHeroProps) {
  const clampedPct = Math.min(Math.max(data.percent, 0), 100);

  return (
    <div className={styles.progressHero}>
      <div className={styles.progressHeroTop}>
        <span className={styles.progressCount}>
          {data.completed_steps}/{data.total_steps} adım tamamlandı
        </span>
        <span className={styles.progressPct}>
          %{clampedPct.toLocaleString('tr-TR', { maximumFractionDigits: 0 })}
        </span>
      </div>
      <div className={styles.progressBarTrack}>
        <div
          className={`${styles.progressBarFill}${data.all_done ? ` ${styles.progressBarFillDone}` : ''}`}
          style={{ width: `${clampedPct}%` }}
        />
      </div>
      <p className={styles.progressEncourage}>{encouragingLine(clampedPct)}</p>
    </div>
  );
}

// --- Celebration card ---

function CelebrationCard() {
  return (
    <div className={styles.celebrationCard}>
      <div className={styles.celebrationTitle}>
        Kurulum tamamlandı! 🎉 Tüm modüller hazır.
      </div>
      <div className={styles.celebrationSubtitle}>
        AYAZ artık tam kapasitesiyle çalışıyor. Verileri takip edin, raporları inceleyin.
      </div>
    </div>
  );
}

// --- Single step row ---

interface StepRowProps {
  step: OnboardingStep;
  index: number;
  isNext: boolean;
}

function StepRow({ step, index, isNext }: StepRowProps) {
  const rowClass = [
    styles.stepRow,
    step.done ? styles.stepRowDone : '',
    !step.done && isNext ? styles.stepRowNext : '',
  ]
    .filter(Boolean)
    .join(' ');

  const circleClass = [
    styles.stepCircle,
    step.done
      ? styles.stepCircleDone
      : isNext
      ? styles.stepCircleNext
      : styles.stepCirclePending,
  ].join(' ');

  return (
    <div className={rowClass}>
      {/* Numbered circle or check mark */}
      <div className={circleClass} aria-hidden="true">
        {step.done ? '✓' : index + 1}
      </div>

      {/* Text body */}
      <div className={styles.stepBody}>
        <div
          className={`${styles.stepTitle}${step.done ? ` ${styles.stepTitleDone}` : ''}`}
        >
          {step.title}
        </div>
        <div className={styles.stepDescription}>{step.description}</div>
      </div>

      {/* CTA */}
      <div className={styles.stepAction}>
        {step.done ? (
          <span className={styles.doneBadge}>Tamamlandı ✓</span>
        ) : (
          <Link
            href={step.cta_link}
            className={`${styles.ctaBtn}${isNext ? ` ${styles.ctaBtnNext}` : ''}`}
          >
            {step.cta_label}
          </Link>
        )}
      </div>
    </div>
  );
}

// --- Steps list ---

function StepsList({ steps }: { steps: OnboardingStep[] }) {
  const nextIdx = firstPendingIndex(steps);

  return (
    <div className={styles.sectionCard}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>Kurulum Adımları</span>
        <span className={styles.stepCount}>
          {steps.filter((s) => s.done).length}/{steps.length} tamamlandı
        </span>
      </div>
      <div className={styles.stepList}>
        {steps.map((step, idx) => (
          <StepRow
            key={step.key}
            step={step}
            index={idx}
            isNext={idx === nextIdx}
          />
        ))}
      </div>
    </div>
  );
}

// --- Main page ---

export default function OnboardingPage() {
  const [data, setData] = useState<OnboardingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getOnboardingStatus();
      setData(result);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : 'Kurulum durumu yüklenemedi',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Kurulum Sihirbazı</h1>
          <p className={styles.pageSubtitle}>
            AYAZ&apos;ı birkaç adımda kurun; her ekibiniz hazır olsun.
          </p>
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <div className={styles.sectionCard}>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchStatus}>
                Tekrar Dene
              </button>
            </div>
          </div>
        ) : data ? (
          <>
            {/* Progress hero */}
            <ProgressHero data={data} />

            {/* Celebration card — shown only when all steps are done */}
            {data.all_done && <CelebrationCard />}

            {/* Steps list */}
            {data.steps.length > 0 ? (
              <StepsList steps={data.steps} />
            ) : (
              <div className={styles.sectionCard}>
                <div className={styles.stateBox}>
                  <span className={styles.muted}>Kurulum adımı bulunamadı.</span>
                </div>
              </div>
            )}
          </>
        ) : null}
      </main>
    </div>
  );
}
