// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import Benchmarks, { BenchmarksView } from '../../ui/src/benchmarks/Benchmarks';
import type { BenchmarksResponse, Scoreboard } from '../../ui/src/benchmarks/derive';

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
    expect(rows[0]!.textContent).toContain('3.0/8');
    expect(rows[0]!.textContent).toContain('5.0/5');
    expect(rows[0]!.textContent).toContain('USD 0.21');
    expect(rows[0]!.textContent).toContain('(same vendor)');
    expect(rows[1]!.textContent).toContain('1.53');
    expect(rows[2]!.textContent).toContain('no result (10 of 10 runs not run)');
  });

  it('shows the proposed order and the recall per case', () => {
    render(createElement(BenchmarksView, { data: withBoard() }));
    expect(screen.getByTestId('bm-proposed').textContent).toContain('claude-sonnet (tier 2: claude-opus), deepseek, glm');
    const recall = screen.getByTestId('bm-recall');
    expect(recall.textContent).toContain('p12');
    expect(recall.textContent).toContain('2 runs each');
    expect(screen.getByText('Source: evals/results/review-scoreboard.json')).toBeTruthy();
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
