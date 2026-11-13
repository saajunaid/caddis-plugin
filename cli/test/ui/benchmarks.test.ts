import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
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
    expect(summaryLine(board())).toBe('Review benchmark - case set: 5 cases (1 large, 4 small) - updated 2026-11-12');
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
});
