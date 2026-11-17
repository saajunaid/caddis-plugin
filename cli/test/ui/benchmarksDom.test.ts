// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import Benchmarks, { BenchmarksView, INTRO } from '../../ui/src/benchmarks/Benchmarks';
import { COLUMNS, type BenchmarksResponse, type Scoreboard } from '../../ui/src/benchmarks/derive';

// jsdom replaces the global URL, so build the path with node:path.
const board = (): Scoreboard =>
  JSON.parse(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../fixtures/review-scoreboard.json'), 'utf8')) as Scoreboard;
const withBoard = (): BenchmarksResponse => ({
  schema: 1,
  boards: [{ repo: 'caddis', path: 'evals/results/review-scoreboard.json', board: board() }],
  errors: [],
});

afterEach(cleanup);

describe('Benchmarks page in the DOM', () => {
  it('renders one table row per board row', () => {
    render(createElement(BenchmarksView, { data: withBoard() }));
    const rows = screen.getAllByTestId('bm-row');
    expect(rows).toHaveLength(3);
    expect(rows[0]!.textContent).toContain('sonnet');
    expect(rows[0]!.textContent).toContain('1.75');
    expect(rows[0]!.textContent).toContain('38%');
    expect(rows[0]!.textContent).toContain('100%');
    expect(rows[0]!.textContent).toContain('USD 0.21');
    expect(rows[0]!.textContent).toContain('(same vendor)');
    expect(rows[1]!.textContent).toContain('1.53');
    expect(rows[2]!.textContent).toContain('no result (10 of 10 runs not run)');
  });

  it('shows the proposed order and the recall per case', () => {
    render(createElement(BenchmarksView, { data: withBoard() }));
    const proposed = screen.getByTestId('bm-proposed');
    expect(proposed.textContent).toContain('Code written by agy');
    expect(proposed.textContent).toContain('claude-sonnet (tier 2: claude-opus)');
    expect(proposed.querySelectorAll('ol')).toHaveLength(2);
    const recall = screen.getByTestId('bm-recall');
    expect(recall.textContent).toContain('p12');
    expect(recall.textContent).toContain('2 runs each');
    expect(screen.getByText('Source: evals/results/review-scoreboard.json')).toBeTruthy();
  });

  it('explains the page: intro, a legend entry per column, column tooltips and a headline', () => {
    render(createElement(BenchmarksView, { data: withBoard() }));
    expect(screen.getByTestId('bm-intro').textContent).toBe(INTRO);
    const legend = screen.getByTestId('bm-legend');
    expect(legend.textContent).toContain('Wrong verdicts');
    expect(legend.textContent).toContain('lower is better');
    expect(legend.querySelectorAll('dt')).toHaveLength(COLUMNS.length);
    const heads = within(screen.getByTestId('bm-table')).getAllByRole('columnheader');
    expect(heads.map((h) => h.textContent)).toContain('Bugs found (large changes)');
    expect(heads.every((h) => (h.getAttribute('title') ?? '').length > 20)).toBe(true);
    expect(screen.getByTestId('bm-headline').textContent).toContain('Best score: sonnet (1.75 of a possible 3).');
  });

  it('marks wrong verdicts and failed runs as warnings and groups the cases by size', () => {
    const b = JSON.parse(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../fixtures/review-scoreboard-6.json'), 'utf8')) as Scoreboard;
    const { container } = render(createElement(BenchmarksView, { data: { schema: 1, boards: [{ repo: 'caddis', path: 'p', board: b }], errors: [] } }));
    expect(container.querySelectorAll('.bm-chip-bad')).toHaveLength(2);
    expect(container.querySelectorAll('.bm-chip-warn')).toHaveLength(2);
    expect(screen.getAllByTestId('bm-row')).toHaveLength(6);
    expect(screen.getAllByTestId('bm-row')[0]!.textContent).toContain('best');
    expect([...container.querySelectorAll('.bm-group')].map((g) => g.textContent)).toEqual(['Large changes', 'Small changes']);
    expect(container.querySelectorAll('.bm-recall-table .bm-case-h')).toHaveLength(10);
  });

  it('benchmarks empty state', () => {
    render(createElement(BenchmarksView, { data: { schema: 1, boards: [], errors: [] } }));
    expect(screen.getByTestId('bm-empty').textContent).toBe('No benchmark yet. Run evals/review_eval.py score.');
    expect(screen.queryByTestId('bm-table')).toBeNull();
  });

  it('shows errors', () => {
    render(createElement(BenchmarksView, { data: { schema: 1, boards: [], errors: [{ repo: 'caddis', error: 'Unexpected token } in JSON' }] } }));
    expect(screen.getByTestId('bm-errors').textContent).toContain('caddis: Unexpected token } in JSON');
    expect(screen.getByTestId('bm-empty')).toBeTruthy();
  });

  it('a board that is not a scoreboard shows the empty state, not a crash', () => {
    render(createElement(BenchmarksView, { data: { schema: 1, boards: [{ repo: 'x', path: 'p', board: 'nope' }], errors: [] } }));
    expect(screen.getByTestId('bm-empty')).toBeTruthy();
  });

  it('loads on mount and shows the table; a failed load shows a notice', async () => {
    render(createElement(Benchmarks, { load: () => Promise.resolve(withBoard()) }));
    await waitFor(() => expect(screen.getByTestId('bm-table')).toBeTruthy());
    cleanup();
    render(createElement(Benchmarks, { load: () => Promise.reject(new Error('x')) }));
    await waitFor(() => expect(screen.getByTestId('bm-failed').textContent).toContain('did not load'));
  });
});
