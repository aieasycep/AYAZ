'use client';

import { useState, useEffect, useCallback } from 'react';
import { getScores, type ScoresResponse, type ScoreComponent, type ScoreRating } from '@/lib/api';
import { parseApiError } from '@/lib/parseApiError';
import { LoadingState, ErrorState, EmptyState } from '@/components/StateViews';
import styles from './PerformanceScore.module.css';

// ---------------------------------------------------------------------------
// Rating helpers
// ---------------------------------------------------------------------------

/**
 * Derive a rating from a 0–100 integer score using the standard thresholds:
 *   ≥ 67 → iyi, 34–66 → orta, < 34 → zayıf
 * Used for component cards (the overall rating comes from the API directly).
 */
function scoreToRating(score: number): ScoreRating {
  if (score >= 67) return 'iyi';
  if (score >= 34) return 'orta';
  return 'zayıf';
}

function ratingPillClass(rating: ScoreRating): string {
  switch (rating) {
    case 'iyi':
      return styles.ratingIyi;
    case 'orta':
      return styles.ratingOrta;
    default:
      return styles.ratingZayif;
  }
}

function ratingFillClass(rating: ScoreRating): string {
  switch (rating) {
    case 'iyi':
      return styles.fillIyi;
    case 'orta':
      return styles.fillOrta;
    default:
      return styles.fillZayif;
  }
}

/** Stroke colour for the SVG arc, derived from the rating. Maps to CSS tokens
 *  via inline style so the gauge respects dark mode correctly. */
function ratingStroke(rating: ScoreRating): string {
  switch (rating) {
    case 'iyi':
      return 'var(--color-success-text)';
    case 'orta':
      return 'var(--color-warning-text)';
    default:
      return 'var(--color-danger-text)';
  }
}

// ---------------------------------------------------------------------------
// Overall circular gauge (SVG, no deps)
// ---------------------------------------------------------------------------

interface OverallGaugeProps {
  score: number;
  rating: ScoreRating;
  label: string;
}

/**
 * A circular gauge drawn with a single SVG <circle> using stroke-dasharray /
 * stroke-dashoffset to fill an arc proportional to `score` (0–100).
 *
 * The circle has r=54 → circumference ≈ 339.3px.
 * We use a 270° visible arc (3/4 of the circle), clipped at the bottom via
 * a rotated coordinate system:  rotate(-225deg) around the centre.
 *
 * Accessibility: role="img" + aria-label per the task spec.
 */
function OverallGauge({ score, rating, label }: OverallGaugeProps) {
  const r = 54;
  const cx = 70;
  const cy = 70;
  const circumference = 2 * Math.PI * r; // ≈ 339.29
  // The arc spans 270° = 75% of circumference
  const arcLength = circumference * 0.75;
  const filled = arcLength * (Math.max(0, Math.min(100, score)) / 100);
  const empty = arcLength - filled;

  // Rotate so the 270° arc starts at bottom-left (−225° from top = 135° CW from right)
  const rotation = -225;

  const ariaLabel = `${label}: ${score}/100, ${rating}`;

  return (
    <div
      className={styles.gaugeWrap}
      role="img"
      aria-label={ariaLabel}
    >
      <svg
        className={styles.gaugeSvg}
        viewBox="0 0 140 140"
        aria-hidden="true"
        focusable="false"
      >
        {/* Background track arc */}
        <circle
          className={styles.gaugeTrack}
          cx={cx}
          cy={cy}
          r={r}
          strokeDasharray={`${arcLength} ${circumference - arcLength}`}
          strokeDashoffset={0}
          transform={`rotate(${rotation} ${cx} ${cy})`}
        />
        {/* Filled arc */}
        <circle
          className={styles.gaugeArc}
          cx={cx}
          cy={cy}
          r={r}
          stroke={ratingStroke(rating)}
          strokeDasharray={`${filled} ${empty + (circumference - arcLength)}`}
          strokeDashoffset={0}
          transform={`rotate(${rotation} ${cx} ${cy})`}
        />
      </svg>
      {/* Score number in the centre */}
      <div className={styles.gaugeScore} aria-hidden="true">
        <span className={styles.gaugeScoreNum}>{score}</span>
        <span className={styles.gaugeScoreOf}>/100</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component card (horizontal progress bar gauge)
// ---------------------------------------------------------------------------

interface ComponentCardProps {
  component: ScoreComponent;
}

function ComponentCard({ component }: ComponentCardProps) {
  const rating = scoreToRating(component.score);
  const ariaLabel = `${component.label}: ${component.score}/100, ${rating}`;

  return (
    <article className={styles.componentCard}>
      <span className={styles.componentLabel}>{component.label}</span>

      {/* Horizontal progress-bar gauge */}
      <div
        className={styles.progressWrap}
        role="img"
        aria-label={ariaLabel}
      >
        <div className={styles.progressBar} aria-hidden="true">
          <div
            className={`${styles.progressFill} ${ratingFillClass(rating)}`}
            style={{ width: `${Math.max(0, Math.min(100, component.score))}%` }}
          />
        </div>
        <span className={styles.progressScore} aria-hidden="true">
          {component.score}
        </span>
      </div>

      {/* Basis: why this score (Turkish explanation from backend) */}
      {component.basis && (
        <p className={styles.basisText} title={component.basis}>
          {component.basis}
        </p>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// Main exported component
// ---------------------------------------------------------------------------

export interface PerformanceScoreProps {
  dateFrom: string;
  dateTo: string;
}

export default function PerformanceScore({ dateFrom, dateTo }: PerformanceScoreProps) {
  const [data, setData] = useState<ScoresResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (from: string, to: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getScores(from, to);
      setData(res);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(dateFrom, dateTo);
  }, [dateFrom, dateTo, fetchData]);

  // Inner body — separate from the card shell so the header always renders
  let body: React.ReactNode;

  if (loading) {
    body = (
      <div className={styles.stateWrapper}>
        <LoadingState message="Performans skoru yükleniyor..." />
      </div>
    );
  } else if (error) {
    body = (
      <div className={styles.stateWrapper}>
        <ErrorState
          message={error}
          onRetry={() => fetchData(dateFrom, dateTo)}
        />
      </div>
    );
  } else if (!data || data.components.length === 0) {
    body = (
      <div className={styles.stateWrapper}>
        <EmptyState title="Bu dönem için skor verisi yok." />
      </div>
    );
  } else {
    body = (
      <div className={styles.body}>
        {/* Left: overall circular gauge */}
        <div className={styles.overallCol}>
          <OverallGauge
            score={data.overall.score}
            rating={data.overall.rating}
            label={data.overall.label}
          />
          <span className={styles.gaugeLabel}>{data.overall.label}</span>
          <span
            className={`${styles.ratingPill} ${ratingPillClass(data.overall.rating)}`}
          >
            {data.overall.rating}
          </span>
        </div>

        {/* Right: component score cards */}
        <div className={styles.componentsCol}>
          {data.components.map((comp) => (
            <ComponentCard key={comp.key} component={comp} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <section className={styles.section} aria-labelledby="perf-score-title">
      <div className={styles.header}>
        <h2 className={styles.title} id="perf-score-title">
          Performans Skoru
        </h2>
        {data && (
          <span className={styles.dateHint}>
            {data.date_from} — {data.date_to}
          </span>
        )}
      </div>
      {body}
    </section>
  );
}
