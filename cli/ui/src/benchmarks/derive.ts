/**
 * The Benchmarks page model. Pure: the scoreboard JSON that `/api/benchmarks` serves (written by
 * `evals/review_eval.py score`) goes in, the cell texts of the page come out.
 */
export interface BenchCase {
  id: string;
  size: string;
  known: number;
  repo?: string | null;
}

export interface BenchPerCase {
  /** Findings found, one number per run. */
  found: number[];
  known: number;
  consistent?: number;
}

export interface BenchRow {
  model: string;
  vendor: string;
  date?: string;
  runs: number;
  not_run: number;
  score: number | null;
  large_recall: number | null;
  small_recall: number | null;
  wrong_verdicts: number | null;
  mean_seconds: number | null;
  cost_per_run_usd: number | null;
  graded_by: string | null;
  same_vendor_grader: boolean;
  per_case: Record<string, BenchPerCase>;
}

export interface Scoreboard {
  schema?: number;
  updated: string;
  cases: BenchCase[];
  rows: BenchRow[];
  proposed: Record<string, string[]>;
}

export interface BenchmarksResponse {
  schema: number;
  boards: { repo: string; path: string; board: unknown }[];
  errors: { repo: string; error: string }[];
}

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

/** A scoreboard from the raw JSON, or null when it is not one. The file is data from disk, so the page never trusts it. */
export function asScoreboard(raw: unknown): Scoreboard | null {
  if (!isObject(raw) || !Array.isArray(raw.rows)) return null;
  const rows = raw.rows.filter(isObject).map((r) => ({ ...r, per_case: isObject(r.per_case) ? r.per_case : {} }) as unknown as BenchRow);
  const cases = Array.isArray(raw.cases) ? (raw.cases.filter(isObject) as unknown as BenchCase[]) : [];
  return {
    updated: typeof raw.updated === 'string' ? raw.updated : '',
    cases,
    rows,
    proposed: isObject(raw.proposed) ? (raw.proposed as Record<string, string[]>) : {},
  };
}

/** Best score first; a row with no score goes last. The sort is stable, so equal rows keep the file order. */
export function sortRows(rows: BenchRow[]): BenchRow[] {
  return [...rows].sort((a, b) => {
    if (a.score === null && b.score === null) return 0;
    if (a.score === null) return 1;
    if (b.score === null) return -1;
    return b.score - a.score;
  });
}

/** Rounds half up on the decimal text, so 1.525 shows as 1.53 (toFixed alone gives 1.52). */
export const score2 = (n: number): string => (Math.round(n * 100) / 100).toFixed(2);

const mean = (xs: number[]): number => (xs.length === 0 ? 0 : xs.reduce((a, b) => a + b, 0) / xs.length);

/** Mean findings found over the runs of one case, as `3.0/8`. A case with no runs counts as 0 found. */
export function caseCell(row: BenchRow, c: BenchCase): string {
  const pc = row.per_case[c.id];
  if (!pc || pc.found.length === 0) return '-';
  return `${mean(pc.found).toFixed(1)}/${pc.known ?? c.known}`;
}

/** The Large or Small cell: mean found over the runs, added up over the cases of that size, over the known findings. */
export function recallCell(row: BenchRow, cases: BenchCase[], size: 'large' | 'small'): string {
  const of = cases.filter((c) => c.size === size);
  if (of.length === 0) return '-';
  let found = 0;
  let known = 0;
  for (const c of of) {
    const pc = row.per_case[c.id];
    found += mean(pc?.found ?? []);
    known += pc?.known ?? c.known;
  }
  return `${found.toFixed(1)}/${known}`;
}

export const costCell = (row: BenchRow): string => (row.cost_per_run_usd === null ? '-' : `USD ${row.cost_per_run_usd.toFixed(2)}`);

export function gradedByCell(row: BenchRow): string {
  if (!row.graded_by) return '-';
  return row.same_vendor_grader ? `${row.graded_by} (same vendor)` : row.graded_by;
}

/** `runs` in a row is the total (cases x runs per case), so the count is not multiplied again. */
export const noResultText = (row: BenchRow): string => `no result (${row.not_run} of ${row.runs} runs not run)`;

export function summaryLine(b: Scoreboard): string {
  const large = b.cases.filter((c) => c.size === 'large').length;
  const small = b.cases.filter((c) => c.size === 'small').length;
  const updated = b.updated ? ` - updated ${b.updated}` : '';
  return `Review benchmark - case set: ${b.cases.length} cases (${large} large, ${small} small)${updated}`;
}

/** Runs per case for the recall table: the most runs any case has. */
export function recallRuns(b: Scoreboard): number {
  let n = 0;
  for (const r of b.rows) for (const pc of Object.values(r.per_case)) n = Math.max(n, pc.found.length);
  return n;
}

/** `claude-sonnet` followed by `claude-opus` is the tier 2 swap: show it as one entry. */
export function orderLine(order: string[]): string {
  const out: string[] = [];
  for (let i = 0; i < order.length; i++) {
    const name = order[i]!;
    if (name === 'claude-sonnet' && order[i + 1] === 'claude-opus') {
      out.push('claude-sonnet (tier 2: claude-opus)');
      i++;
    } else out.push(name);
  }
  return out.join(', ');
}

const WRITER: Record<string, string> = { anthropic: 'claude', google: 'agy' };

export function proposedLines(b: Scoreboard): { label: string; order: string }[] {
  return Object.entries(b.proposed).map(([vendor, order]) => ({
    label: `${WRITER[vendor] ?? vendor}-written code`,
    order: orderLine(Array.isArray(order) ? order : []),
  }));
}
