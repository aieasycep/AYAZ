// Briefing API — typed wrappers for /api/v1/briefings/*

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';

const TOKEN_KEY = 'ayaz_token';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

async function authFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const url = `${API_BASE}${path}`;

  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token ?? ''}`,
      ...options?.headers,
    },
  });

  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = '/login';
    }
    throw new Error('Oturum süresi doldu');
  }

  if (!res.ok) {
    const detail = await res.text().catch(() => 'İstek başarısız');
    throw new Error(detail || 'İstek başarısız');
  }

  return res.json() as Promise<T>;
}

// --- Types ---

export type GoalStatus = 'on_track' | 'at_risk' | 'off_track';

export interface PerformanceDelta {
  spend?: { value: number; prev: number; pct: number };
  roas?: { value: number; prev: number; pct: number };
  conversions?: { value: number; prev: number; pct: number };
  [key: string]: { value: number; prev: number; pct: number } | undefined;
}

export interface TopInsight {
  severity: 'critical' | 'warning' | 'info';
  title: string;
}

export interface TopRecommendation {
  message: string;
  suggested_action: string;
}

export interface GoalStatusItem {
  name: string;
  status: GoalStatus;
  forecast: string;
}

export interface BriefingBody {
  performance_delta: PerformanceDelta;
  top_insights: TopInsight[];
  top_recommendation: TopRecommendation;
  goals_status: GoalStatusItem[];
}

export interface Briefing {
  id: string;
  briefing_date: string; // ISO date
  headline: string;
  body: BriefingBody;
}

export interface BriefingSummary {
  id: string;
  briefing_date: string;
  headline: string;
}

// --- Normalisation ---
// Backend returns performance_delta as {yesterday:{spend,roas,conversions},
// prior_day:{...}, delta:{spend_pct,roas_pct,conversions_pct}}. The UI expects a
// per-metric map {spend:{value,prev,pct}, ...}. Normalise here so the page stays simple.
function normaliseBriefing(b: Briefing): Briefing {
  const pd = (b?.body?.performance_delta ?? {}) as Record<string, unknown>;
  if (pd && (pd.yesterday || pd.prior_day || pd.delta)) {
    const y = (pd.yesterday ?? {}) as Record<string, number>;
    const p = (pd.prior_day ?? {}) as Record<string, number>;
    const d = (pd.delta ?? {}) as Record<string, number>;
    const norm: Record<string, { value: number; prev: number; pct: number }> = {};
    for (const m of ['spend', 'roas', 'conversions']) {
      if (y[m] !== undefined || p[m] !== undefined) {
        // backend delta is a fraction (1.0 = +100%); UI's fmtPct appends '%' without scaling
        norm[m] = { value: y[m] ?? 0, prev: p[m] ?? 0, pct: (d[`${m}_pct`] ?? 0) * 100 };
      }
    }
    b.body.performance_delta = norm as unknown as PerformanceDelta;
  }

  // Backend goals_status items are
  // {goal_id, name, metric, target_value, current_value, pct_to_target,
  //  forecast_value, status, recommendation}. The UI reads {name, status, forecast}.
  // Map a readable `forecast` line (prefer the recommendation text).
  const gs = b?.body?.goals_status as unknown;
  if (Array.isArray(gs)) {
    b.body.goals_status = gs.map((g) => {
      const item = (g ?? {}) as Record<string, unknown>;
      const forecast =
        typeof item.forecast === 'string'
          ? (item.forecast as string)
          : typeof item.recommendation === 'string'
            ? (item.recommendation as string)
            : item.forecast_value != null
              ? String(item.forecast_value)
              : '';
      return { ...item, forecast } as unknown as GoalStatusItem;
    });
  } else {
    b.body.goals_status = [];
  }

  // Guard arrays the page calls `.length`/`.map` on.
  if (!Array.isArray(b?.body?.top_insights)) {
    b.body.top_insights = [];
  }
  // Guard the object the page passes to Object.entries().
  if (b?.body && (b.body.performance_delta == null || typeof b.body.performance_delta !== 'object')) {
    b.body.performance_delta = {} as PerformanceDelta;
  }

  return b;
}

// --- API calls ---

export async function getLatestBriefing(): Promise<Briefing> {
  return normaliseBriefing(await authFetch<Briefing>('/api/v1/briefings/latest'));
}

export function getBriefings(): Promise<BriefingSummary[]> {
  return authFetch<BriefingSummary[]>('/api/v1/briefings');
}

export async function generateBriefing(): Promise<Briefing> {
  return normaliseBriefing(
    await authFetch<Briefing>('/api/v1/briefings/generate', { method: 'POST' }),
  );
}
