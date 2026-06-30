'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import AppNav from '@/components/AppNav';
import {
  getHealthIndex,
  GRADE_LABELS,
  type HealthIndex,
  type HealthDimension,
  type HealthGrade,
} from '@/lib/health-index-api';
import styles from './health-index.module.css';

// --- Helpers ---

function gradeClass(grade: HealthGrade): string {
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

function ringFillClass(grade: HealthGrade): string {
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

function miniRingFillClass(grade: HealthGrade): string {
  switch (grade) {
    case 'mukemmel':
      return styles.miniRingFillMukemmel;
    case 'iyi':
      return styles.miniRingFillIyi;
    case 'orta':
      return styles.miniRingFillOrta;
    case 'zayif':
      return styles.miniRingFillZayif;
    default:
      return styles.miniRingFillMukemmel;
  }
}

// --- SVG score ring (hero) ---

const RING_R = 55;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_R;

interface ScoreRingProps {
  score: number;
  grade: HealthGrade;
}

function ScoreRing({ score, grade }: ScoreRingProps) {
  const offset =
    RING_CIRCUMFERENCE * (1 - Math.min(Math.max(score, 0), 100) / 100);
  return (
    <div className={styles.scoreRing}>
      <svg
        className={styles.scoreRingCircle}
        viewBox="0 0 130 130"
        aria-hidden="true"
      >
        <circle
          className={styles.scoreRingTrack}
          cx="65"
          cy="65"
          r={RING_R}
        />
        <circle
          className={ringFillClass(grade)}
          cx="65"
          cy="65"
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

// --- Mini SVG ring for dimension cards ---

const MINI_R = 20;
const MINI_CIRCUMFERENCE = 2 * Math.PI * MINI_R;

interface MiniRingProps {
  score: number;
  grade: HealthGrade;
}

function MiniRing({ score, grade }: MiniRingProps) {
  const offset =
    MINI_CIRCUMFERENCE * (1 - Math.min(Math.max(score, 0), 100) / 100);
  return (
    <div className={styles.miniRing}>
      <svg
        className={styles.miniRingCircle}
        viewBox="0 0 50 50"
        aria-hidden="true"
      >
        <circle
          className={styles.miniRingTrack}
          cx="25"
          cy="25"
          r={MINI_R}
        />
        <circle
          className={miniRingFillClass(grade)}
          cx="25"
          cy="25"
          r={MINI_R}
          strokeDasharray={MINI_CIRCUMFERENCE}
          strokeDashoffset={offset}
        />
      </svg>
      <div className={styles.miniScoreNumber}>{score}</div>
    </div>
  );
}

// --- Dimension card ---

interface DimCardProps {
  dim: HealthDimension;
}

function DimCard({ dim }: DimCardProps) {
  const isVeriYok = dim.status === 'veri_yok';
  const cardCls = `${styles.dimCard} ${isVeriYok ? styles.dimCardMuted : ''}`;

  return (
    <Link href={dim.href} className={cardCls}>
      <div className={styles.dimCardHeader}>
        <span className={styles.dimLabel}>{dim.label}</span>
        {isVeriYok || dim.score === null || dim.grade === null ? (
          <div className={styles.miniRing}>
            <div className={styles.miniScoreDash}>—</div>
          </div>
        ) : (
          <MiniRing score={dim.score} grade={dim.grade} />
        )}
      </div>

      <div className={styles.dimCardBody}>
        <div className={styles.dimGradeRow}>
          {isVeriYok || dim.grade === null ? (
            <span className={styles.veriYokChip}>Veri yok</span>
          ) : (
            <span className={`${styles.gradeBadge} ${gradeClass(dim.grade)}`}>
              {GRADE_LABELS[dim.grade]}
            </span>
          )}
        </div>
        <p className={styles.dimDetail}>{dim.detail}</p>
      </div>
    </Link>
  );
}

// --- Loading skeleton ---

function LoadingSkeleton() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonHero}`} />
      <div className={styles.skeletonGrid}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className={`${styles.skeleton} ${styles.skeletonCard}`}
          />
        ))}
      </div>
    </>
  );
}

// --- Main page ---

export default function HealthIndexPage() {
  const [data, setData] = useState<HealthIndex | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getHealthIndex();
      setData(result);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : 'Sağlık endeksi yüklenemedi',
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Pazarlama Sağlık Endeksi</h1>
          <p className={styles.pageSubtitle}>
            Tüm kanalların stratejik sağlık puanı — reklam, içerik, ölçümleme ve daha fazlası 6 boyutta.
          </p>
          <p className={styles.pageNote}>
            Bu sayfa stratejik puanlamayı gösterir. Teknik sorunlar için{' '}
            <a href="/audit" className={styles.pageNoteLink}>Hesap Sağlık Taraması</a>
            {' '}sayfasını ziyaret edin.
          </p>
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <div className={styles.errorCard}>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchData}>
                Tekrar Dene
              </button>
            </div>
          </div>
        ) : data ? (
          <>
            {/* Hero score card */}
            <div className={styles.heroCard}>
              <ScoreRing
                score={data.overall_score}
                grade={data.overall_grade}
              />

              <div className={styles.heroDetails}>
                <div className={styles.gradeRow}>
                  <span
                    className={`${styles.gradeBadge} ${gradeClass(data.overall_grade)}`}
                  >
                    {GRADE_LABELS[data.overall_grade]}
                  </span>
                </div>

                <div className={styles.summaryChips}>
                  <span className={styles.chipStrong}>{data.summary.strong_count} güçlü</span>
                  <span className={styles.chipSep}>·</span>
                  <span className={styles.chipWeak}>{data.summary.weak_count} zayıf</span>
                  <span className={styles.chipSep}>·</span>
                  <span className={styles.chipNeutral}>{data.summary.scored_count} boyut</span>
                </div>
              </div>
            </div>

            {/* Dimensions grid */}
            <div className={styles.dimensionsGrid}>
              {data.dimensions.map((dim) => (
                <DimCard key={dim.key} dim={dim} />
              ))}
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
