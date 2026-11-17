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

/** A later list price and the day it starts. */
export interface BenchNextPrice {
  from: string;
  input: number;
  output: number;
}

/** The public list price of one reviewer, in USD per 1M tokens. */
export interface BenchPrice {
  priced_model?: string;
  input: number;
  output: number;
  source?: string;
  as_of?: string;
  next?: BenchNextPrice;
}

export interface Scoreboard {
  schema?: number;
  updated: string;
  cases: BenchCase[];
  rows: BenchRow[];
  proposed: Record<string, string[]>;
  /** Price per reviewer id. A reviewer with no entry has no price. */
  prices: Record<string, BenchPrice>;
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
    prices: asPrices(raw.prices),
  };
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const isDay = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v);

/** The price entries that are well formed. A bad entry is dropped, so that reviewer shows a dash. */
function asPrices(raw: unknown): Record<string, BenchPrice> {
  const out: Record<string, BenchPrice> = {};
  if (!isObject(raw)) return out;
  for (const [model, p] of Object.entries(raw)) {
    if (!isObject(p) || !isNum(p.input) || !isNum(p.output)) continue;
    const price: BenchPrice = { input: p.input, output: p.output };
    if (typeof p.priced_model === 'string') price.priced_model = p.priced_model;
    if (typeof p.source === 'string') price.source = p.source;
    if (typeof p.as_of === 'string') price.as_of = p.as_of;
    const n = p.next;
    if (isObject(n) && isDay(n.from) && isNum(n.input) && isNum(n.output)) price.next = { from: n.from, input: n.input, output: n.output };
    out[model] = price;
  }
  return out;
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

/** Today as `YYYY-MM-DD`, the form the price dates use. */
export const todayText = (): string => new Date().toISOString().slice(0, 10);

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** `2026-12-01` as `1 Dec 2026`. Text that is not a date comes back as it is. */
export function dayText(day: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
  return m && month ? `${Number(m[3])} ${month} ${m[1]}` : day;
}

const pair = (input: number, output: number): string => `${input.toFixed(2)} / ${output.toFixed(2)}`;

/** The price in force on `today`: the later price once its start day has come. */
export function currentPrice(price: BenchPrice | undefined, today: string = todayText()): { input: number; output: number } | null {
  if (!price) return null;
  return price.next && today >= price.next.from ? price.next : price;
}

/** The price cell: `2.00 / 10.00` (USD per 1M tokens, input / output), or a dash when the reviewer has no price. */
export function priceCell(price: BenchPrice | undefined, today: string = todayText()): string {
  const p = currentPrice(price, today);
  return p ? pair(p.input, p.output) : '-';
}

/** The price that starts later, as `4.00 / 20.00 from 1 Dec 2026`, or null when none is waiting. */
export function nextPriceText(price: BenchPrice | undefined, today: string = todayText()): string | null {
  if (!price?.next || today >= price.next.from) return null;
  return `${pair(price.next.input, price.next.output)} from ${dayText(price.next.from)}`;
}

/** One note line per price rise that has not started yet, naming the reviewers it hits. */
export function priceRiseNotes(b: Scoreboard, today: string = todayText()): string[] {
  const groups = new Map<string, { models: string[]; text: string }>();
  for (const r of b.rows) {
    const price = b.prices[r.model];
    if (!price?.next || today >= price.next.from) continue;
    const text = `${price.priced_model ?? r.model}: the list price rises on ${dayText(price.next.from)}, from ${pair(price.input, price.output)} to ${pair(price.next.input, price.next.output)}.`;
    const g = groups.get(text) ?? { models: [], text };
    g.models.push(r.model);
    groups.set(text, g);
  }
  return [...groups.values()].map((g) => `${g.text} This hits ${g.models.join(', ')}.`);
}

export function gradedByCell(row: BenchRow): string {
  if (!row.graded_by) return '-';
  return row.same_vendor_grader ? `${row.graded_by} (same vendor)` : row.graded_by;
}

/** `runs` in a row is the total (cases x runs per case), so the count is not multiplied again. */
export const noResultText = (row: BenchRow): string => `no result (${row.not_run} of ${row.runs} runs not run)`;

export function summaryLine(b: Scoreboard): string {
  const large = b.cases.filter((c) => c.size === 'large').length;
  const small = b.cases.filter((c) => c.size === 'small').length;
  const updated = b.updated ? ` Updated ${b.updated}.` : '';
  return `${b.rows.length} reviewers tried the same ${b.cases.length} code changes (${large} large, ${small} small).${updated}`;
}

/** Share of known bugs found, as a whole-number percent: 0.375 gives `38%`. */
export const pct = (n: number | null | undefined): string => (n === null || n === undefined ? '-' : `${Math.round(n * 100)}%`);

/**
 * The recall of one size as a 0-1 share. The row field is the one the score uses, so it wins; a row without the
 * field gets the share worked out from its per-case counts. A row with no score has no share.
 */
export function recallShare(row: BenchRow, cases: BenchCase[], size: 'large' | 'small'): number | null {
  if (row.score === null) return null;
  const field = size === 'large' ? row.large_recall : row.small_recall;
  if (typeof field === 'number') return field;
  let found = 0;
  let known = 0;
  for (const c of cases.filter((x) => x.size === size)) {
    found += mean(row.per_case[c.id]?.found ?? []);
    known += row.per_case[c.id]?.known ?? c.known;
  }
  return known === 0 ? null : found / known;
}

/** 2 x large recall + 1 x small recall, both at 100%. */
export const MAX_SCORE = 3;

/** Bar width in percent for a score: 0 or less is empty, the best possible score is full. */
export const scoreBarPct = (score: number | null): number => (score === null || score <= 0 ? 0 : Math.min(100, Math.round((score / MAX_SCORE) * 100)));

/** Time per review in plain units: `45 s`, `2 min 11 s`. */
export function timeCell(seconds: number | null): string {
  if (seconds === null) return '-';
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r === 0 ? `${m} min` : `${m} min ${r} s`;
}

export type Tone = 'good' | 'warn' | 'bad';

/** The headline of a board: the best reviewer, then every reviewer with a wrong verdict, then every one with failed runs. */
export function headlineLines(b: Scoreboard): { tone: Tone; text: string }[] {
  const out: { tone: Tone; text: string }[] = [];
  const scored = sortRows(b.rows).filter((r) => r.score !== null);
  const best = scored[0];
  if (best) {
    const tied = scored.filter((r) => r.score === best.score);
    out.push({
      tone: 'good',
      text:
        tied.length > 1
          ? `Best score (tie, ${score2(best.score!)}): ${tied.map((r) => r.model).join(', ')}.`
          : `Best score: ${best.model} (${score2(best.score!)} of a possible ${MAX_SCORE}).`,
    });
  } else out.push({ tone: 'warn', text: 'No reviewer has a score yet.' });
  const wrong = b.rows.filter((r) => (r.wrong_verdicts ?? 0) > 0);
  if (wrong.length > 0) {
    out.push({ tone: 'bad', text: `Approved code that has a known bug: ${wrong.map((r) => `${r.model} (${r.wrong_verdicts})`).join(', ')}.` });
  } else if (scored.length > 0) out.push({ tone: 'good', text: 'No reviewer approved code that has a known bug.' });
  const failed = b.rows.filter((r) => r.not_run > 0);
  if (failed.length > 0) {
    out.push({ tone: 'warn', text: `Reviews that failed and gave no result: ${failed.map((r) => `${r.model} (${r.not_run} of ${r.runs})`).join(', ')}.` });
  }
  return out;
}

/** The meaning of every column, for the legend and the header tooltips. */
export interface Column {
  id: string;
  label: string;
  help: string;
  better: 'higher' | 'lower' | null;
}
export const COLUMNS: Column[] = [
  { id: 'reviewer', label: 'Reviewer', help: 'The AI model that reviews the code. The line below the name shows its vendor and the date of the run.', better: null },
  {
    id: 'score',
    label: 'Score',
    help: 'One number for the whole test: 2 x the share of bugs found on large changes, plus 1 x the share found on small changes, minus the wrong verdicts per full pass over all the code changes (for example 7 wrong verdicts in 2 passes take 3.5 off). The best possible score is 3. The score can go below 0.',
    better: 'higher',
  },
  { id: 'large', label: 'Bugs found (large changes)', help: 'The share of known bugs the reviewer found in the large code changes. Large changes count double in the score.', better: 'higher' },
  { id: 'small', label: 'Bugs found (small changes)', help: 'The share of known bugs the reviewer found in the small code changes.', better: 'higher' },
  {
    id: 'wrong',
    label: 'Wrong verdicts',
    help: 'How many times the reviewer said APPROVE on code that has a known bug. This is the most harmful mistake, and each one lowers the score. 0 is best.',
    better: 'lower',
  },
  { id: 'failed', label: 'Failed runs', help: 'Reviews that did not finish (a time-out or an API error) and gave no result. Shown as failed out of all runs.', better: 'lower' },
  { id: 'time', label: 'Time per review', help: 'The average time the reviewer needs for one review.', better: 'lower' },
  {
    id: 'price',
    label: 'Price per 1M tokens (in / out)',
    help: 'The public list price of the model, in USD, for every 1 million tokens it reads (in) and writes (out). Output includes the thinking tokens. A lower price is cheaper, but compare it with the score. Your company contract may differ.',
    better: 'lower',
  },
  {
    id: 'cost',
    label: 'Cost per review',
    help: 'The average price of one review, in USD: the tokens it used times the price. It is measured for the Claude reviewers. A dash means the cost was not measured, so use the price column.',
    better: 'lower',
  },
  {
    id: 'graded',
    label: 'Graded by',
    help: 'The model that checked each report against the list of known bugs. It comes from a different vendor than the reviewer, unless the cell says "same vendor".',
    better: null,
  },
];
/** The line under the column list in the legend: what the two price columns are, and what they are not. */
export const PRICE_LEGEND =
  'Prices are public list prices in USD, not what your company pays: a company contract may differ. Cost per review is what one review used, in tokens times price. It is not measured for the agy reviewers yet, so compare them by price.';
export const column = (id: string): Column => COLUMNS.find((c) => c.id === id)!;

export interface CaseGroup {
  size: string;
  label: string;
  cases: BenchCase[];
}

const sizeRank = (s: string): number => (s === 'large' ? 0 : s === 'small' ? 1 : 2);

/** The cases grouped by size: large first, then small, then any other size. The file order holds inside a group. */
export function groupCases(cases: BenchCase[]): CaseGroup[] {
  const sizes = [...new Set(cases.map((c) => c.size))].sort((a, b) => sizeRank(a) - sizeRank(b));
  return sizes.map((size) => ({ size, label: `${size.charAt(0).toUpperCase()}${size.slice(1)} changes`, cases: cases.filter((c) => c.size === size) }));
}

/** How one reviewer did on one case: all bugs, some, none, or no data (every run failed). */
export function caseTone(row: BenchRow, c: BenchCase): 'full' | 'some' | 'none' | 'na' {
  const pc = row.per_case[c.id];
  if (!pc || pc.found.length === 0) return 'na';
  const m = mean(pc.found);
  if (m >= (pc.known ?? c.known)) return 'full';
  return m > 0 ? 'some' : 'none';
}

/** Runs per case for the recall table: the most runs any case has. */
export function recallRuns(b: Scoreboard): number {
  let n = 0;
  for (const r of b.rows) for (const pc of Object.values(r.per_case)) n = Math.max(n, pc.found.length);
  return n;
}

/** `claude-sonnet` followed by `claude-opus` is the tier 2 swap: show it as one entry. */
export function orderSteps(order: string[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < order.length; i++) {
    const name = order[i]!;
    if (name === 'claude-sonnet' && order[i + 1] === 'claude-opus') {
      out.push('claude-sonnet (tier 2: claude-opus)');
      i++;
    } else out.push(name);
  }
  return out;
}

export const orderLine = (order: string[]): string => orderSteps(order).join(', ');

const WRITER: Record<string, string> = { anthropic: 'claude', google: 'agy' };

export function proposedLines(b: Scoreboard): { label: string; order: string }[] {
  return Object.entries(b.proposed).map(([vendor, order]) => ({
    label: `${WRITER[vendor] ?? vendor}-written code`,
    order: orderLine(Array.isArray(order) ? order : []),
  }));
}

const AUTHOR: Record<string, string> = { anthropic: 'Claude', google: 'agy' };

/** One entry per author vendor: who wrote the code, and the reviewers to ask, first choice first. */
export function proposedLists(b: Scoreboard): { author: string; steps: string[] }[] {
  return Object.entries(b.proposed).map(([vendor, order]) => ({
    author: AUTHOR[vendor] ?? vendor,
    steps: orderSteps(Array.isArray(order) ? order : []),
  }));
}
