import { useEffect, useState, type ReactNode } from 'react';
import { getBenchmarks } from '../api';
import './benchmarks.css';
import {
  asScoreboard,
  caseCell,
  caseTone,
  column,
  COLUMNS,
  costCell,
  gradedByCell,
  groupCases,
  headlineLines,
  noResultText,
  pct,
  proposedLists,
  recallCell,
  recallRuns,
  recallShare,
  score2,
  scoreBarPct,
  sortRows,
  summaryLine,
  timeCell,
  type BenchRow,
  type BenchmarksResponse,
  type Scoreboard,
} from './derive';

export const EMPTY_TEXT = 'No benchmark yet. Run evals/review_eval.py score.';

export const INTRO = [
  'This page tests AI models as code reviewers.',
  'Each model reviews the same code changes, and every change has known bugs.',
  'We count how many bugs each model finds, how often it approves bad code, and how long it takes.',
].join(' ');

type ChipTone = 'good' | 'warn' | 'bad' | 'plain';

function Chip({ tone, children, title }: { tone: ChipTone; children: ReactNode; title?: string }): JSX.Element {
  return (
    <span className={`bm-chip bm-chip-${tone}`} title={title}>
      {children}
    </span>
  );
}

/** A percent with a thin bar under it. The bar is a cue only; the number carries the value. */
function Share({ value, title }: { value: number | null; title: string }): JSX.Element {
  if (value === null) return <>-</>;
  return (
    <span className="bm-share" title={title}>
      <span className="bm-share-n">{pct(value)}</span>
      <span className="bm-bar" aria-hidden="true">
        <span style={{ width: `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%` }} />
      </span>
    </span>
  );
}

/** The "How to read this" legend: one entry per column, with the direction that is better. */
function Legend(): JSX.Element {
  return (
    <details className="bm-legend" open data-testid="bm-legend">
      <summary>How to read this</summary>
      <dl className="bm-legend-list">
        {COLUMNS.map((c) => (
          <div key={c.id} className="bm-legend-item">
            <dt>
              {c.label}
              {c.better && <span className={`bm-dir bm-dir-${c.better}`}>{c.better === 'higher' ? 'higher is better' : 'lower is better'}</span>}
            </dt>
            <dd>{c.help}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function Th({ id }: { id: string }): JSX.Element {
  const c = column(id);
  const dir = c.better ? ` (${c.better} is better)` : '';
  return (
    <th scope="col" title={`${c.help}${dir}`} className={id === 'reviewer' || id === 'graded' ? undefined : 'bm-num'}>
      {c.label}
    </th>
  );
}

function ReviewerRow({ r, board, best }: { r: BenchRow; board: Scoreboard; best: boolean }): JSX.Element {
  const meta = [r.vendor, r.date].filter(Boolean).join(' - ');
  const name = (
    <th scope="row">
      <span className="bm-name">
        {r.model}
        {best && <Chip tone="good">best</Chip>}
      </span>
      {meta && <span className="bm-meta">{meta}</span>}
    </th>
  );
  if (r.score === null) {
    return (
      <tr data-testid="bm-row">
        {name}
        <td className="bm-num">-</td>
        <td colSpan={7} className="bm-none">
          {noResultText(r)}
        </td>
      </tr>
    );
  }
  const wrong = r.wrong_verdicts ?? 0;
  return (
    <tr data-testid="bm-row">
      {name}
      <td className="bm-num">
        <span className="bm-share" title={`Score ${score2(r.score)} of a possible 3`}>
          <span className={`bm-share-n bm-score${r.score < 0 ? ' neg' : ''}`}>{score2(r.score)}</span>
          <span className="bm-bar" aria-hidden="true">
            <span style={{ width: `${scoreBarPct(r.score)}%` }} />
          </span>
        </span>
      </td>
      <td className="bm-num">
        <Share value={recallShare(r, board.cases, 'large')} title={`${recallCell(r, board.cases, 'large')} known bugs found on average (large changes)`} />
      </td>
      <td className="bm-num">
        <Share value={recallShare(r, board.cases, 'small')} title={`${recallCell(r, board.cases, 'small')} known bugs found on average (small changes)`} />
      </td>
      <td className="bm-num">
        {wrong > 0 ? (
          <Chip tone="bad" title="This reviewer approved code that has a known bug">
            {`! ${wrong}`}
          </Chip>
        ) : (
          <span className="bm-ok">0</span>
        )}
      </td>
      <td className="bm-num">
        {r.not_run > 0 ? (
          <Chip tone="warn" title={`${r.not_run} of ${r.runs} reviews failed and gave no result`}>
            {`! ${r.not_run} of ${r.runs}`}
          </Chip>
        ) : (
          <span className="bm-ok">0</span>
        )}
      </td>
      <td className="bm-num" title={r.mean_seconds === null ? undefined : `${Math.round(r.mean_seconds)} seconds`}>
        {timeCell(r.mean_seconds)}
      </td>
      <td className="bm-num" title={r.cost_per_run_usd === null ? 'Cost was not measured' : undefined}>
        {costCell(r)}
      </td>
      <td>{r.same_vendor_grader && r.graded_by ? <Chip tone="plain">{gradedByCell(r)}</Chip> : gradedByCell(r)}</td>
    </tr>
  );
}

const TONE_TEXT = { full: 'all found', some: 'some found', none: 'none found', na: 'no result' } as const;

function Board({ board, source, repo }: { board: Scoreboard; source: string; repo: string | null }): JSX.Element {
  const rows = sortRows(board.rows);
  const runs = recallRuns(board);
  const proposed = proposedLists(board);
  const groups = groupCases(board.cases);
  const bestModel = rows[0] && rows[0].score !== null ? rows[0].model : null;
  return (
    <section className="bm-board" data-testid="bm-board">
      {repo && <h2 className="bm-repo">{repo}</h2>}
      <div className="bm-block">
        <h2 className="bm-h">Result</h2>
        <p className="page-subtitle" data-testid="bm-summary">
          {summaryLine(board)}
        </p>
        <ul className="bm-headline" data-testid="bm-headline">
          {headlineLines(board).map((h, i) => (
            <li key={i} className={`bm-headline-${h.tone}`}>
              {h.text}
            </li>
          ))}
        </ul>
      </div>

      <div className="bm-scroll">
        <table className="bm-table" data-testid="bm-table">
          <thead>
            <tr>
              <Th id="reviewer" />
              <Th id="score" />
              <Th id="large" />
              <Th id="small" />
              <Th id="wrong" />
              <Th id="failed" />
              <Th id="time" />
              <Th id="cost" />
              <Th id="graded" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <ReviewerRow key={r.model} r={r} board={board} best={r.model === bestModel} />
            ))}
          </tbody>
        </table>
      </div>

      {proposed.length > 0 && (
        <div className="bm-block" data-testid="bm-proposed">
          <h2 className="bm-h">Suggested reviewer order</h2>
          <p className="bm-help">
            Based on these results, this is the order in which to ask reviewers for each kind of author, first choice first. The reviewer
            should come from a different vendor than the author.
          </p>
          <div className="bm-proposed">
            {proposed.map((p) => (
              <div key={p.author} className="bm-proposed-card">
                <h3 className="bm-proposed-h">Code written by {p.author}</h3>
                <ol className="bm-steps">
                  {p.steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bm-block" data-testid="bm-recall">
        <h2 className="bm-h">
          Bugs found per code change
          {runs > 0 && <span className="bm-note"> ({runs} runs each)</span>}
        </h2>
        <p className="bm-help">
          Each column is one code change. A cell shows how many of its known bugs the reviewer found, on average over the runs, as found / known.
          Green: all found. Amber: some found. Red: none found. A dash means every run failed. Large changes come first.
        </p>
        <div className="bm-scroll">
          <table className="bm-table bm-recall-table">
            <thead>
              <tr className="bm-group-row">
                <th scope="col" rowSpan={2}>
                  Reviewer
                </th>
                {groups.map((g) => (
                  <th key={g.size} scope="colgroup" colSpan={g.cases.length} className={`bm-group bm-group-${g.size}`}>
                    {g.label}
                  </th>
                ))}
              </tr>
              <tr>
                {groups.flatMap((g) =>
                  g.cases.map((c) => (
                    <th
                      key={c.id}
                      scope="col"
                      className="bm-case-h"
                      title={`${c.id}: ${c.size} change, ${c.known} known ${c.known === 1 ? 'bug' : 'bugs'}${c.repo ? ` (${c.repo} repo)` : ''}`}
                    >
                      <span className="bm-case-id">{c.id}</span>
                      <span className="bm-case-n">
                        {c.known} {c.known === 1 ? 'bug' : 'bugs'}
                      </span>
                    </th>
                  )),
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.model}>
                  <th scope="row">{r.model}</th>
                  {groups.flatMap((g) =>
                    g.cases.map((c) => {
                      const tone = caseTone(r, c);
                      return (
                        <td key={c.id} className="bm-num">
                          {tone === 'na' ? (
                            <span title={TONE_TEXT.na}>-</span>
                          ) : (
                            <span className={`bm-case bm-case-${tone}`} title={`${c.id}: ${TONE_TEXT[tone]}`}>
                              {caseCell(r, c)}
                            </span>
                          )}
                        </td>
                      );
                    }),
                  )}
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
      <p className="bm-intro" data-testid="bm-intro">
        {INTRO}
      </p>
      <Legend />
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
