import { useEffect, useState } from 'react';
import { getBenchmarks } from '../api';
import './benchmarks.css';
import {
  asScoreboard,
  caseCell,
  costCell,
  gradedByCell,
  noResultText,
  proposedLines,
  recallCell,
  recallRuns,
  score2,
  sortRows,
  summaryLine,
  type BenchmarksResponse,
  type Scoreboard,
} from './derive';

export const EMPTY_TEXT = 'No benchmark yet. Run evals/review_eval.py score.';

function Board({ board, source, repo }: { board: Scoreboard; source: string; repo: string | null }): JSX.Element {
  const rows = sortRows(board.rows);
  const runs = recallRuns(board);
  const proposed = proposedLines(board);
  return (
    <section className="bm-board" data-testid="bm-board">
      {repo && <h2 className="bm-repo">{repo}</h2>}
      <p className="page-subtitle">{summaryLine(board)}</p>
      <div className="bm-scroll">
        <table className="bm-table" data-testid="bm-table">
          <thead>
            <tr>
              <th scope="col">Reviewer</th>
              <th scope="col">Score</th>
              <th scope="col">Large</th>
              <th scope="col">Small</th>
              <th scope="col">Wrong</th>
              <th scope="col">Mean s</th>
              <th scope="col">Cost/run</th>
              <th scope="col">Graded by</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.model} data-testid="bm-row">
                <th scope="row">{r.model}</th>
                {r.score === null ? (
                  <>
                    <td>-</td>
                    <td colSpan={6} className="bm-none">
                      {noResultText(r)}
                    </td>
                  </>
                ) : (
                  <>
                    <td className="bm-num">{score2(r.score)}</td>
                    <td className="bm-num">{recallCell(r, board.cases, 'large')}</td>
                    <td className="bm-num">{recallCell(r, board.cases, 'small')}</td>
                    <td className="bm-num">{r.wrong_verdicts ?? '-'}</td>
                    <td className="bm-num">{r.mean_seconds === null ? '-' : Math.round(r.mean_seconds)}</td>
                    <td className="bm-num">{costCell(r)}</td>
                    <td>{gradedByCell(r)}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {proposed.length > 0 && (
        <div className="bm-block" data-testid="bm-proposed">
          <h2 className="bm-h">Proposed order</h2>
          <ul className="bm-list">
            {proposed.map((p) => (
              <li key={p.label}>
                <span className="bm-label">{p.label}:</span> {p.order}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="bm-block" data-testid="bm-recall">
        <h2 className="bm-h">
          Recall per case
          {runs > 0 && <span className="bm-note"> ({runs} runs each)</span>}
        </h2>
        <div className="bm-scroll">
          <table className="bm-table bm-recall-table">
            <thead>
              <tr>
                <th scope="col">Reviewer</th>
                {board.cases.map((c) => (
                  <th key={c.id} scope="col" title={`${c.size} case`}>
                    {c.id}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.model}>
                  <th scope="row">{r.model}</th>
                  {board.cases.map((c) => (
                    <td key={c.id} className="bm-num">
                      {caseCell(r, c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <p className="bm-source">Source: {source}</p>
    </section>
  );
}

/** The page body for one response. A board that is not a scoreboard is skipped; no board left gives the empty state. */
export function BenchmarksView({ data }: { data: BenchmarksResponse }): JSX.Element {
  const boards = data.boards.flatMap((b) => {
    const board = asScoreboard(b.board);
    return board ? [{ ...b, board }] : [];
  });
  return (
    <div className="bm" data-testid="benchmarks">
      <div className="page-header">
        <h1 className="page-title">Benchmarks</h1>
      </div>
      {data.errors.length > 0 && (
        <ul className="lane-note bm-errors" data-testid="bm-errors">
          {data.errors.map((e, i) => (
            <li key={i}>
              {e.repo}: {e.error}
            </li>
          ))}
        </ul>
      )}
      {boards.length === 0 ? (
        <p className="col-empty" data-testid="bm-empty">
          {EMPTY_TEXT}
        </p>
      ) : (
        boards.map((b) => <Board key={`${b.repo}/${b.path}`} board={b.board} source={b.path} repo={boards.length > 1 ? b.repo : null} />)
      )}
    </div>
  );
}

/** The Benchmarks page: reads `/api/benchmarks` once when it opens (the page is rarely open, and the data changes by hand). */
export default function Benchmarks({ load = getBenchmarks }: { load?: () => Promise<BenchmarksResponse> }): JSX.Element {
  const [data, setData] = useState<BenchmarksResponse | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    load().then(
      (d) => live && setData(d),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [load]);

  if (data) return <BenchmarksView data={data} />;
  return (
    <div className="bm" data-testid="benchmarks">
      <div className="page-header">
        <h1 className="page-title">Benchmarks</h1>
      </div>
      {failed ? (
        <p className="lane-note" data-testid="bm-failed">
          The benchmark data did not load. Reload the page to try again.
        </p>
      ) : (
        <p className="page-subtitle">Loading...</p>
      )}
    </div>
  );
}
