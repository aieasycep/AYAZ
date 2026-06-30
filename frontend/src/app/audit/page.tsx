'use client';

import { useState, useEffect, useCallback } from 'react';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import {
  runAudit,
  GRADE_LABELS,
  type AuditReport,
  type AuditCategory,
  type AuditCheck,
  type AuditGrade,
} from '@/lib/audit-api';
import styles from './audit.module.css';

// --- Helpers ---

function gradeClass(grade: AuditGrade): string {
  switch (grade) {
    case 'mukemmel':
      return styles.gradeMukemmel;
    case 'iyi':
      return styles.gradeIyi;
    case 'orta':
      return styles.gradeOrta;
    case 'zayif':
      return styles.gradeZayif;
    default:
      return styles.gradeMukemmel;
  }
}

function ringFillClass(grade: AuditGrade): string {
  switch (grade) {
    case 'mukemmel':
      return styles.scoreRingFillMukemmel;
    case 'iyi':
      return styles.scoreRingFillIyi;
    case 'orta':
      return styles.scoreRingFillOrta;
    case 'zayif':
      return styles.scoreRingFillZayif;
    default:
      return styles.scoreRingFillMukemmel;
  }
}

// --- SVG ring score ---

// r=50 → circumference = 2π·50 ≈ 314.16
const RING_R = 50;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_R;

interface ScoreRingProps {
  score: number;
  grade: AuditGrade;
}

function ScoreRing({ score, grade }: ScoreRingProps) {
  const offset = RING_CIRCUMFERENCE * (1 - Math.min(Math.max(score, 0), 100) / 100);
  return (
    <div className={styles.scoreRing}>
      <svg
        className={styles.scoreRingCircle}
        viewBox="0 0 120 120"
        aria-hidden="true"
      >
        <circle
          className={styles.scoreRingTrack}
          cx="60"
          cy="60"
          r={RING_R}
        />
        <circle
          className={ringFillClass(grade)}
          cx="60"
          cy="60"
          r={RING_R}
          strokeDasharray={RING_CIRCUMFERENCE}
          strokeDashoffset={offset}
        />
      </svg>
      <div>
        <div className={styles.scoreNumber}>{score}</div>
        <div className={styles.scoreOutOf}>/100</div>
      </div>
    </div>
  );
}

// --- Severity icon ---

function SeverityIcon({ severity }: { severity: AuditCheck['severity'] }) {
  const cls =
    severity === 'pass'
      ? styles.severityPass
      : severity === 'warn'
      ? styles.severityWarn
      : styles.severityFail;
  const symbol = severity === 'pass' ? '✓' : severity === 'warn' ? '⚠' : '✕';
  return (
    <span className={`${styles.severityIcon} ${cls}`} aria-label={severity}>
      {symbol}
    </span>
  );
}

// --- Individual check row ---

function CheckRow({ check }: { check: AuditCheck }) {
  const rowCls =
    check.severity === 'warn'
      ? `${styles.checkRow} ${styles.checkRowWarn}`
      : check.severity === 'fail'
      ? `${styles.checkRow} ${styles.checkRowFail}`
      : styles.checkRow;

  return (
    <div className={rowCls}>
      <SeverityIcon severity={check.severity} />
      <div className={styles.checkContent}>
        <div className={styles.checkTitle}>{check.title}</div>
        <div className={styles.checkFinding}>{check.finding}</div>
        {(check.severity === 'warn' || check.severity === 'fail') && (
          <div className={styles.checkRecommendation}>
            <span className={styles.checkRecommendationLabel}>Öneri:</span>
            {check.recommendation}
          </div>
        )}
      </div>
    </div>
  );
}

// --- Category card ---

function CategoryCard({ category }: { category: AuditCategory }) {
  const passCount = category.checks.filter((c) => c.severity === 'pass').length;
  const warnCount = category.checks.filter((c) => c.severity === 'warn').length;
  const failCount = category.checks.filter((c) => c.severity === 'fail').length;

  const badgeCls =
    failCount > 0
      ? styles.sectionCountBadgeFail
      : warnCount > 0
      ? styles.sectionCountBadgeWarn
      : styles.sectionCountBadge;

  const badgeText =
    failCount > 0
      ? `${failCount} sorun · ${warnCount} uyarı · ${passCount} geçti`
      : warnCount > 0
      ? `${warnCount} uyarı · ${passCount} geçti`
      : `${passCount} geçti`;

  return (
    <div className={styles.sectionCard}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>{category.label}</span>
        <span className={`${styles.sectionCountBadge} ${badgeCls}`}>
          {badgeText}
        </span>
      </div>
      <div className={styles.checkList}>
        {category.checks.map((check) => (
          <CheckRow key={check.id} check={check} />
        ))}
      </div>
    </div>
  );
}

// --- Loading skeleton ---

function LoadingSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonHero}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// --- Main page ---

export default function AuditPage() {
  const [data, setData] = useState<AuditReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAudit = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await runAudit();
      setData(result);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : 'Hesap taraması yüklenemedi',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAudit();
  }, [fetchAudit]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Hesap Sağlık Taraması</h1>
          <p className={styles.pageSubtitle}>
            Reklam, ölçümleme, bütçe, içerik ve hedeflerinizi tek tıkla
            tarayın; sorunları ve çözümleri görün.
          </p>
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <SectionCard>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchAudit}>
                Tekrar Dene
              </button>
            </div>
          </SectionCard>
        ) : data ? (
          <>
            {/* Hero score card */}
            <div className={styles.heroCard}>
              <ScoreRing score={data.score} grade={data.grade} />

              <div className={styles.heroDetails}>
                <div className={styles.gradeRow}>
                  <span
                    className={`${styles.gradeBadge} ${gradeClass(data.grade)}`}
                  >
                    {GRADE_LABELS[data.grade]}
                  </span>
                </div>

                <p className={styles.heroSummary}>{data.summary}</p>

                <div className={styles.countsRow}>
                  <span className={`${styles.countItem} ${styles.countPass}`}>
                    ✓ {data.counts.pass} geçti
                  </span>
                  <span className={styles.countDivider} aria-hidden="true">
                    ·
                  </span>
                  <span className={`${styles.countItem} ${styles.countWarn}`}>
                    ⚠ {data.counts.warn} uyarı
                  </span>
                  <span className={styles.countDivider} aria-hidden="true">
                    ·
                  </span>
                  <span className={`${styles.countItem} ${styles.countFail}`}>
                    ✕ {data.counts.fail} sorun
                  </span>
                </div>
              </div>

              <div className={styles.heroActions}>
                <button
                  className={styles.rescanBtn}
                  onClick={fetchAudit}
                  disabled={loading}
                >
                  Yeniden Tara
                </button>
              </div>
            </div>

            {/* Category cards */}
            <div className={styles.categoryGrid}>
              {data.categories.map((category) => (
                <CategoryCard key={category.key} category={category} />
              ))}
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
