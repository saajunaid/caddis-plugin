import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  asScoreboard,
  caseTone,
  currentPrice,
  dayText,
  nextPriceText,
  priceCell,
  priceRiseNotes,
  groupCases,
  headlineLines,
  pct,
  proposedLists,
  recallShare,
  scoreBarPct,
  timeCell,
  costCell,
  gradedByCell,
  noResultText,
  orderLine,
  proposedLines,
  recallCell,
  recallRuns,
  sortRows,
  summaryLine,
  type BenchRow,
  type Scoreboard,
} from '../../ui/src/benchmarks/derive';
import { parseRoute } from '../../ui/src/shell/route';

const board = (): Scoreboard => JSON.parse(readFileSync(new URL('../fixtures/review-scoreboard.json', import.meta.url), 'utf8')) as Scoreboard;
const board6 = (): Scoreboard => JSON.parse(readFileSync(new URL('../fixtures/review-scoreboard-6.json', import.meta.url), 'utf8')) as Scoreboard;
const rowOf = (b: Scoreboard, model: string): BenchRow => b.rows.find((r) => r.model === model)!;

describe('benchmarks route', () => {
  it('parseRoute gives the benchmarks page', () => {
    expect(parseRoute('#/benchmarks')).toEqual({ page: 'benchmarks' });
  });
});

describe('benchmarks derive', () => {
  it('rows sorted by score, null last', () => {
    const b = board();
    const shuffled = [b.rows[2]!, b.rows[1]!, b.rows[0]!];
    expect(sortRows(shuffled).map((r) => r.model)).toEqual(['sonnet', 'opus', 'agy-carbon-high']);
    const nulls = [rowOf(b, 'agy-carbon-high'), { ...rowOf(b, 'opus'), score: 0 }];
    expect(sortRows(nulls).map((r) => r.model)).toEqual(['opus', 'agy-carbon-high']);
  });

  it('large cell is mean found / known', () => {
    const b = board();
    expect(recallCell(rowOf(b, 'sonnet'), b.cases, 'large')).toBe('3.0/8');
    expect(recallCell(rowOf(b, 'opus'), b.cases, 'large')).toBe('2.5/8');
  });

  it('small cell is the sum of the mean found over the small cases', () => {
    const b = board();
    expect(recallCell(rowOf(b, 'sonnet'), b.cases, 'small')).toBe('5.0/5');
    expect(recallCell(rowOf(b, 'opus'), b.cases, 'small')).toBe('4.5/5');
  });

  it('a size with no case gives a dash', () => {
    const b = board();
    expect(recallCell(rowOf(b, 'sonnet'), b.cases.filter((c) => c.size === 'small'), 'large')).toBe('-');
  });

  it('cost cell', () => {
    const b = board();
    expect(costCell(rowOf(b, 'sonnet'))).toBe('USD 0.21');
    expect(costCell(rowOf(b, 'opus'))).toBe('USD 0.55');
    expect(costCell(rowOf(b, 'agy-carbon-high'))).toBe('-');
  });

  it('price cell is input / output per 1M tokens, a dash without a price', () => {
    const b = board6();
    expect(priceCell(b.prices.sonnet, '2026-11-17')).toBe('2.00 / 10.00');
    expect(priceCell(b.prices.opus, '2026-11-17')).toBe('4.00 / 20.00');
    expect(priceCell(b.prices['agy-hydrogen-high'], '2026-11-17')).toBe('1.50 / 7.50');
    expect(priceCell(undefined, '2026-11-17')).toBe('-');
  });

  it('Carbon price rises on 1 Dec 2026: the later price waits, then it is the current one', () => {
    const carbon = board6().prices['agy-carbon-medium'];
    expect(priceCell(carbon, '2026-11-30')).toBe('2.00 / 10.00');
    expect(nextPriceText(carbon, '2026-11-30')).toBe('4.00 / 20.00 from 1 Dec 2026');
    expect(priceCell(carbon, '2026-12-01')).toBe('4.00 / 20.00');
    expect(nextPriceText(carbon, '2026-12-01')).toBeNull();
    expect(currentPrice(undefined, '2026-11-30')).toBeNull();
    expect(nextPriceText(board6().prices.sonnet, '2026-11-30')).toBeNull();
  });

  it('price notes name the reviewers a coming rise hits, and vanish once it starts', () => {
    const b = board6();
    expect(priceRiseNotes(b, '2026-11-17')).toEqual([
      'gemini-4-carbon: the list price rises on 1 Dec 2026, from 2.00 / 10.00 to 4.00 / 20.00. This hits agy-carbon-medium, agy-carbon-high.',
    ]);
    expect(priceRiseNotes(b, '2026-12-01')).toEqual([]);
    expect(priceRiseNotes(board(), '2026-11-17')).toHaveLength(1);
  });

  it('day text, and a bad price entry is dropped by asScoreboard', () => {
    expect(dayText('2026-12-01')).toBe('1 Dec 2026');
    expect(dayText('soon')).toBe('soon');
    const raw = { ...board6(), prices: { sonnet: { input: 2, output: 'x' }, opus: { input: 4, output: 20, next: { from: 'soon', input: 1, output: 1 } } } };
    const b = asScoreboard(raw)!;
    expect(Object.keys(b.prices)).toEqual(['opus']);
    expect(b.prices.opus!.next).toBeUndefined();
    expect(asScoreboard({ rows: [] })!.prices).toEqual({});
  });

  it('same-vendor grader label', () => {
    const b = board();
    expect(gradedByCell({ ...rowOf(b, 'sonnet'), graded_by: 'opus' })).toBe('opus (same vendor)');
    expect(gradedByCell({ ...rowOf(b, 'sonnet'), graded_by: 'agy-carbon-medium', same_vendor_grader: false })).toBe('agy-carbon-medium');
    expect(gradedByCell(rowOf(b, 'agy-carbon-high'))).toBe('-');
  });

  it('no result text counts the runs not run', () => {
    expect(noResultText(rowOf(board(), 'agy-carbon-high'))).toBe('no result (10 of 10 runs not run)');
  });

  it('summary line names the case set and the date', () => {
    expect(summaryLine(board())).toBe('3 reviewers tried the same 5 code changes (1 large, 4 small). Updated 2026-11-12.');
  });

  it('recall runs is the most runs any case has', () => {
    expect(recallRuns(board())).toBe(2);
  });

  it('proposed order is one line per vendor with the tier 2 swap folded in', () => {
    expect(proposedLines(board())).toEqual([
      { label: 'claude-written code', order: 'agy-carbon, deepseek, glm' },
      { label: 'agy-written code', order: 'claude-sonnet (tier 2: claude-opus), deepseek, glm' },
    ]);
    expect(orderLine(['zed', 'claude-opus'])).toBe('zed, claude-opus');
  });

  it('percent text rounds to a whole number and a missing value is a dash', () => {
    expect(pct(0.375)).toBe('38%');
    expect(pct(1)).toBe('100%');
    expect(pct(0)).toBe('0%');
    expect(pct(null)).toBe('-');
    expect(pct(undefined)).toBe('-');
  });

  it('recall share uses the row field and falls back to the per-case counts', () => {
    const b = board();
    expect(recallShare(rowOf(b, 'sonnet'), b.cases, 'large')).toBe(0.375);
    const noField = { ...rowOf(b, 'sonnet'), large_recall: null, small_recall: null };
    expect(recallShare(noField, b.cases, 'large')).toBeCloseTo(3 / 8);
    expect(recallShare(noField, b.cases, 'small')).toBe(1);
    expect(recallShare(rowOf(b, 'agy-carbon-high'), b.cases, 'large')).toBeNull();
  });

  it('score bar is empty at 0 or below and full at the best possible score', () => {
    expect(scoreBarPct(null)).toBe(0);
    expect(scoreBarPct(-2.6)).toBe(0);
    expect(scoreBarPct(1.5)).toBe(50);
    expect(scoreBarPct(3)).toBe(100);
    expect(scoreBarPct(9)).toBe(100);
  });

  it('time cell uses plain units', () => {
    expect(timeCell(null)).toBe('-');
    expect(timeCell(45.4)).toBe('45 s');
    expect(timeCell(131)).toBe('2 min 11 s');
    expect(timeCell(120)).toBe('2 min');
  });

  it('headline names the best reviewer, wrong verdicts and failed runs from the data', () => {
    const lines = headlineLines(board6());
    expect(lines.map((l) => l.tone)).toEqual(['good', 'bad', 'warn']);
    expect(lines[0]!.text).toBe('Best score: opus (1.61 of a possible 3).');
    expect(lines[1]!.text).toBe('Approved code that has a known bug: sonnet (1), agy-hydrogen-medium (7).');
    expect(lines[2]!.text).toBe(
      'Reviews that failed and gave no result: agy-carbon-medium (4 of 20), agy-hydrogen-high (4 of 20), agy-carbon-high (10 of 10).',
    );
  });

  it('headline for a clean board, a board with no score and a tie', () => {
    const b = board();
    const clean = headlineLines({ ...b, rows: [rowOf(b, 'sonnet')] });
    expect(clean.map((l) => l.text)).toEqual(['Best score: sonnet (1.75 of a possible 3).', 'No reviewer approved code that has a known bug.']);
    expect(headlineLines({ ...b, rows: [rowOf(b, 'agy-carbon-high')] }).map((l) => l.tone)).toEqual(['warn', 'warn']);
    const tie = headlineLines({ ...b, rows: [rowOf(b, 'sonnet'), { ...rowOf(b, 'opus'), score: 1.75 }] });
    expect(tie[0]!.text).toBe('Best score (tie, 1.75): sonnet, opus.');
  });

  it('cases are grouped large first and each cell has a tone', () => {
    const b = board6();
    const groups = groupCases(b.cases);
    expect(groups.map((g) => [g.label, g.cases.length])).toEqual([
      ['Large changes', 5],
      ['Small changes', 5],
    ]);
    expect(groups[0]!.cases[0]!.id).toBe('p12');
    const c = (id: string) => b.cases.find((x) => x.id === id)!;
    expect(caseTone(rowOf(b, 'opus'), c('h2'))).toBe('full');
    expect(caseTone(rowOf(b, 'opus'), c('p12'))).toBe('some');
    expect(caseTone(rowOf(b, 'opus'), c('fleet-1'))).toBe('none');
    expect(caseTone(rowOf(b, 'agy-carbon-medium'), c('fleet-5'))).toBe('na');
  });

  it('proposed lists name the author and keep the order', () => {
    expect(proposedLists(board())).toEqual([
      { author: 'Claude', steps: ['agy-carbon', 'deepseek', 'glm'] },
      { author: 'agy', steps: ['claude-sonnet (tier 2: claude-opus)', 'deepseek', 'glm'] },
    ]);
  });
});
