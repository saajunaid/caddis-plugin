import { Circle, CircleCheck, Loader, OctagonAlert, Search, ArrowRightLeft } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { repoLabel } from '../inbox/derive';
import { clockText } from '../shell/format';
import { repoId as repoIdOf, repoTabHref } from '../shell/route';
import { localTime } from '../shell/time';
import type { HubState, RepoState } from '../types';
import {
  deriveRoadmaps,
  filterRoadmap,
  listRow,
  NO_ROADMAP_HINT,
  NO_ROADMAP_TEXT,
  opensDirectly,
  TILE_LABEL,
  type Match,
  type MilestoneView,
  type PhaseView,
  type PlanView,
  type RepoRoadmaps,
  type RoadmapModel,
  type Tile,
} from './roadmap';

const TILE_ICON: Record<Tile, typeof Circle> = {
  todo: Circle,
  'in-progress': Loader,
  done: CircleCheck,
  moved: ArrowRightLeft,
  blocked: OctagonAlert,
};
const ICON = { size: 14, 'aria-hidden': true } as const;

function TileIcon({ tile }: { tile: Tile }): JSX.Element {
  const Icon = TILE_ICON[tile];
  return <Icon {...ICON} />;
}

function Bar({ done, total }: { done: number; total: number }): JSX.Element {
  const pct = total ? Math.round((100 * done) / total) : 0;
  return (
    <div className="rm-bar-wrap">
      <div className="rm-bar" role="img" aria-label={`${done} of ${total} phases done`}>
        <i style={{ width: `${pct}%` }} />
      </div>
      <span className="rm-bar-text">
        {done}/{total} phases · {pct}%
      </span>
    </div>
  );
}

/** PR links and the stage of one phase (R46). A number with no GitHub slot is plain text. */
function PhasePrs({ phase }: { phase: PhaseView }): JSX.Element {
  return (
    <>
      {phase.prs.map((p) =>
        p.url ? (
          <a key={p.number} className="rm-pr mono" data-testid="rm-pr" href={p.url} target="_blank" rel="noreferrer noopener">
            #{p.number}
          </a>
        ) : (
          <span key={p.number} className="rm-pr mono" data-testid="rm-pr">
            #{p.number}
          </span>
        ),
      )}
      <span className={`rm-stage tile-${phase.tile}`} data-testid="rm-stage">
        {phase.stage}
      </span>
    </>
  );
}

function Pill({ status }: { status: string }): JSX.Element {
  const done = status === 'done' || status === 'not-needed';
  return <span className={`chip ${done ? 'chip-resolved' : status === 'in-progress' ? 'chip-waiting' : 'chip-hub'}`}>{status}</span>;
}

/** Jump to a milestone: open it and scroll to it. Hash links stay free for the router. */
function openMilestone(slug: string, id: string): void {
  const el = document.getElementById(`ms-${slug}-${id}`);
  if (el instanceof HTMLDetailsElement) el.open = true;
  el?.scrollIntoView({ block: 'start' });
}

function Timeline({ m, match }: { m: RoadmapModel; match: Match | null }): JSX.Element {
  const shown = (p: PhaseView): boolean => !match || match.phases.has(p.ref);
  const cols = m.milestones.length;
  return (
    <section className="rm-section" data-testid="rm-timeline" aria-label="Timeline">
      <h3 className="flow-h">Timeline</h3>
      <div className="rm-timeline-grid" style={{ ['--rm-cols' as string]: cols }}>
        <div className="rm-head-row">
          <div className="rm-cell rm-head rm-lane">Plan / milestone</div>
          {m.milestones.map((ms) => (
            <div key={ms.id} className="rm-cell rm-head">
              <strong>{ms.id}</strong> <Pill status={ms.status} />
              <span className="rm-sub">{ms.depends.length ? `after ${ms.depends.join(', ')}` : 'starts first'}</span>
              {ms.blockers.length > 0 && <span className="rm-gate-count">{ms.blockers.length} gate(s)</span>}
            </div>
          ))}
        </div>
        {m.lanes.map((lane) => (
          <div key={lane.plan} className="rm-row">
            <div className="rm-cell rm-lane">
              {lane.plan}
              <span className="rm-sub">
                {lane.done}/{lane.total} done
              </span>
            </div>
            {m.milestones.map((ms) => (
              <div key={ms.id} className="rm-cell">
                {ms.phases
                  .filter((p) => p.plan === lane.plan && shown(p))
                  .map((p) => (
                    <div key={p.ref} className="rm-tile" data-state={p.tile} data-risk={p.highRisk ? 'high' : undefined} title={`${p.ref} ${p.name} | ${p.tracker || p.stage}`}>
                      <TileIcon tile={p.tile} />
                      <b className="mono">{p.num}</b>
                      <span>{p.name}</span>
                      <span className="sr-only">{TILE_LABEL[p.tile]}</span>
                      {p.highRisk && <i className="rm-risk" aria-label="high risk" />}
                    </div>
                  ))}
              </div>
            ))}
          </div>
        ))}
        {m.blockers.length > 0 && (
          <div className="rm-row">
            <div className="rm-cell rm-lane">Owner and outside</div>
            {m.milestones.map((ms) => (
              <div key={ms.id} className="rm-cell">
                {ms.blockers.map((b, i) => (
                  <div key={i} className="rm-gate-note" title={b.reason}>
                    {b.type}: {b.reason.length > 60 ? `${b.reason.slice(0, 60)}…` : b.reason}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="rm-timeline-list" data-testid="rm-timeline-list">
        {m.milestones.map((ms) => (
          <div key={ms.id}>
            <h4 className="rm-list-h">
              {ms.id} <Pill status={ms.status} />
            </h4>
            {ms.phases.filter(shown).map((p) => (
              <div key={p.ref} className="rm-tile" data-state={p.tile} data-risk={p.highRisk ? 'high' : undefined}>
                <TileIcon tile={p.tile} />
                <b className="mono">
                  {p.plan} {p.num}
                </b>
                <span>{p.name}</span>
                <span className="sr-only">{TILE_LABEL[p.tile]}</span>
                {p.highRisk && <i className="rm-risk" aria-label="high risk" />}
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="rm-legend" data-testid="rm-legend">
        <span>to do · in progress · done · moved · blocked: each tile has an icon and a label</span>
        <span>red dot = Risk high (stops for review)</span>
      </div>
    </section>
  );
}

function Milestones({ m, match }: { m: RoadmapModel; match: Match | null }): JSX.Element {
  return (
    <section className="rm-section" data-testid="rm-milestones" aria-label="Milestones and phases">
      <h3 className="flow-h">Milestones and phases</h3>
      {m.milestones
        .filter((ms) => !match || match.milestones.has(ms.id))
        .map((ms) => (
          <details key={`${ms.id}-${match ? 'q' : 'n'}`} className="rm-ms" id={`ms-${m.slug}-${ms.id}`} open={match ? true : undefined}>
            <summary>
              <strong>{ms.id}</strong> <Pill status={ms.status} />
              <span className="rm-sub">
                owner {ms.owner}
                {ms.target ? ` · target ${ms.target}` : ''} · after {ms.depends.join(', ') || '-'}
              </span>
            </summary>
            {ms.phases.length === 0 ? (
              <p className="col-empty">No build phases.</p>
            ) : (
              <ul className="flow-list">
                {ms.phases
                  .filter((p) => !match || match.phases.has(p.ref))
                  .map((p) => (
                    <li key={p.ref} className="flow-row" data-testid="rm-phase" data-state={p.tile}>
                      <div className="flow-row-head">
                        <code className="mono">{p.ref}</code>
                        <span className="flow-title">{p.name}</span>
                        <PhasePrs phase={p} />
                      </div>
                      <span className="flow-why">
                        {[p.model && `model ${p.model}`, p.lane && `lane ${p.lane.split(' ')[0]}`, p.risk && `risk ${p.risk}`].filter(Boolean).join(' · ') || 'no model, lane or risk recorded'}
                        {p.tracker ? ` · Tracker: ${p.tracker}` : ''}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </details>
        ))}
    </section>
  );
}

function Detail({ m, repo, crumbHref, match }: { m: RoadmapModel; repo: RepoState; crumbHref: string | null; match: Match | null }): JSX.Element {
  const k = m.kpis;
  const jump = (id: string) => () => openMilestone(m.slug, id);
  return (
    <div className="rm-detail" data-testid="rm-detail">
      <nav className="rm-crumbs" data-testid="rm-crumbs" aria-label="Breadcrumb">
        {crumbHref ? <a href={crumbHref}>Roadmaps</a> : <span>Roadmaps</span>} › <span>{repoLabel(repo)}</span> › <strong>{m.slug}</strong>
      </nav>
      {m.detailError && (
        <div className="lane-note" data-testid="rm-errors">
          Roadmap detail is unavailable: {m.detailError}. Phase names, Tracker cells and PR links are missing.
        </div>
      )}
      <header data-testid="rm-header">
        <h2 className="rm-title">Roadmap {m.slug}</h2>
        <p className="page-subtitle">
          {k.milestonesDone} of {k.milestonesTotal} milestones · {k.phasesDone} of {k.phasesTotal} phases done
          {m.branch ? <> · branch <code>{m.branch}</code></> : null}
          {m.originCommit ? <> · origin <code>{m.originCommit}</code></> : null}
        </p>
        {m.lanes.length > 0 && (
          <div className="rm-chips" data-testid="rm-chips">
            {m.lanes.map((l) => (
              <span key={l.plan} className="rm-chip">
                <b>{l.plan}</b> <span className="mono">{l.done}/{l.total} phases</span>
              </span>
            ))}
          </div>
        )}
      </header>

      <section className={`rm-section rm-waiting${m.gates.length ? ' has' : ''}`} data-testid="rm-waiting" aria-label="Waiting for you">
        <h3 className="flow-h">Waiting for you</h3>
        {m.gates.length === 0 ? (
          <p className="col-empty">No owner gate is waiting.</p>
        ) : (
          <ul className="flow-list">
            {m.gates.map((g, i) => (
              <li key={i} className="flow-row">
                <div className="flow-row-head">
                  <strong>{g.milestone}</strong>
                  <span className="chip chip-owner-gate">owner-gate</span>
                </div>
                <span className="flow-why">{g.reason}</span>
                {g.check && <code className="mono">{g.check}</code>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rm-kpis kpi-strip" data-testid="rm-kpis" aria-label="Summary">
        <div className="kpi-tile">
          <span className="kpi-label">Phases done</span>
          <span className="kpi-num">{k.phasesDone} / {k.phasesTotal}</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-label">Milestones done</span>
          <span className="kpi-num">{k.milestonesDone} / {k.milestonesTotal}</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-label">In progress</span>
          <span className="kpi-num">{k.inProgress.length}</span>
          <span className="kpi-sub tone-muted">{k.inProgress.join(', ') || 'none'}</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-label">High-risk phases</span>
          <span className={`kpi-num${k.highRisk ? ' bad' : ''}`}>{k.highRisk}</span>
        </div>
        <div className="kpi-tile deploy">
          <span className="kpi-label">Next batch for the runner</span>
          <span className="kpi-val">{k.next}</span>
        </div>
      </section>

      <section className="rm-section" data-testid="rm-flow" aria-label="Flow">
        <h3 className="flow-h">Flow</h3>
        <div className="rm-chain">
          {m.milestones.map((ms, i) => (
            <span key={ms.id} className="rm-chain-item">
              {i > 0 && <span aria-hidden="true">→</span>}
              <button type="button" className={`rm-node tone-${ms.tone}`} onClick={jump(ms.id)}>
                <b>{ms.id}</b> <Pill status={ms.status} />
                <span className="rm-sub">
                  {ms.depends.length ? `after ${ms.depends.join(', ')}` : 'starts first'} · {ms.done}/{ms.total} ph
                </span>
              </button>
            </span>
          ))}
        </div>
      </section>

      <section className="rm-section" data-testid="rm-board" aria-label="Now, next, later">
        <h3 className="flow-h">Now, next, later</h3>
        <div className="rm-cols">
          {(['now', 'next', 'later'] as const).map((col) => (
            <div key={col}>
              <h4 className="rm-list-h">{col[0]!.toUpperCase() + col.slice(1)}</h4>
              {m.board[col].length === 0 ? (
                <p className="col-empty">none</p>
              ) : (
                m.board[col].map((ms: MilestoneView) => (
                  <button key={ms.id} type="button" className={`rm-rcard tone-${ms.tone}`} onClick={jump(ms.id)}>
                    <span>
                      <strong>{ms.id}</strong> <Pill status={ms.status} />
                    </span>
                    <Bar done={ms.done} total={ms.total} />
                    {ms.blockers.map((b, i) => (
                      <span key={i} className="rm-sub">
                        {b.type}
                      </span>
                    ))}
                  </button>
                ))
              )}
            </div>
          ))}
        </div>
      </section>

      <Timeline m={m} match={match} />

      <section className="rm-section" data-testid="rm-gates" aria-label="Gates and blockers">
        <h3 className="flow-h">Gates and blockers · {m.blockers.length} open</h3>
        {m.blockers.length === 0 ? (
          <p className="col-empty">No blockers.</p>
        ) : (
          <ul className="flow-list">
            {m.blockers.map((b, i) => (
              <li key={i} className="flow-row">
                <div className="flow-row-head">
                  <strong>{b.milestone}</strong>
                  <span className={`chip ${b.type === 'owner-gate' ? 'chip-owner-gate' : 'chip-hub'}`}>{b.type}</span>
                </div>
                <span className="flow-why">{b.reason}</span>
                {b.check && <code className="mono">{b.check}</code>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <Milestones m={m} match={match} />

      <section className="rm-section" data-testid="rm-runner" aria-label="Runner">
        <h3 className="flow-h">Runner</h3>
        {m.runner.running ? (
          <p>
            Running batch <code>{m.runner.running.batch}</code>
            {m.runner.running.since ? ` since ${localTime(m.runner.running.since)}` : ''}
            {m.runner.running.host ? ` (host ${m.runner.running.host}${m.runner.running.pid ? `, pid ${m.runner.running.pid}` : ''})` : ''}.
          </p>
        ) : (
          <p className="col-empty">No runner holds this roadmap now.</p>
        )}
        {m.runner.staleBatch !== null && (
          <p>
            A stale runner lock remains (batch <code>{m.runner.staleBatch}</code>): the runner that held it is gone.
          </p>
        )}
        {m.runner.lastStop && (
          <p>
            Last stop record: {m.runner.lastStopAt ? `${localTime(m.runner.lastStopAt)}: ` : ''}
            {m.runner.lastStop}.
          </p>
        )}
        {m.runner.errors.map((e) => (
          <p key={e} className="tone-warn">
            Could not read {e}.
          </p>
        ))}
        {m.runner.next && (
          <p>
            Next batch: <code>{m.runner.next}</code>
          </p>
        )}
      </section>
    </div>
  );
}

function ListView({ repo, m }: { repo: RepoState; m: RepoRoadmaps }): JSX.Element {
  const id = repoIdOf(repo);
  return (
    <div className="rm-list-view">
      {(m.errors.length > 0 || m.repoError || m.roadmaps.some((r) => r.detailError)) && (
        <div className="lane-note" data-testid="rm-errors">
          {m.repoError && <div>Could not read this repo: {m.repoError}</div>}
          {m.errors.map((e) => (
            <div key={e.slug}>
              Could not read {e.slug}: {e.error}
            </div>
          ))}
          {m.roadmaps
            .filter((r) => r.detailError)
            .map((r) => (
              <div key={r.slug}>
                Detail unavailable for {r.slug}: {r.detailError}
              </div>
            ))}
        </div>
      )}
      <ul className="flow-list rm-cards" data-testid="rm-list" aria-label="Roadmaps">
        {m.roadmaps.map((r) => {
          const row = listRow(r);
          return (
            <li key={r.slug}>
              <a className={`rm-rcard rm-card tone-${row.tone}`} data-testid="rm-card" href={repoTabHref(id, 'roadmap', r.slug)}>
                <span>
                  <strong>{row.slug}</strong> <span className="rm-sub">{row.branch ?? ''}</span>
                </span>
                <Bar done={row.phasesDone} total={row.phasesTotal} />
                <span className="rm-sub">
                  {row.milestonesDone}/{row.milestonesTotal} milestones
                </span>
                <span className="rm-dots">
                  {row.dots.map((d) => (
                    <span key={d.id} className={`rm-dot s-${d.status}`}>
                      {d.id}
                    </span>
                  ))}
                </span>
                <span className="rm-sub">
                  next: {row.next} · runner: {row.runner}
                  {row.gates > 0 ? ` · ${row.gates} open gate${row.gates === 1 ? '' : 's'}` : ''}
                </span>
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Plans({ plans }: { plans: PlanView[] }): JSX.Element {
  return (
    <div className="flow" data-testid="rm-plans">
      <p className="page-subtitle">No roadmap here. These plans are active.</p>
      {plans.map((p) => (
        <section key={p.path} className="flow-section" aria-label={p.title}>
          <h3 className="flow-h">
            {p.title} · {p.open} open
          </h3>
          <ul className="flow-list">
            {p.rows.map((r) => (
              <li key={r.phase} className="flow-row">
                <div className="flow-row-head">
                  <code className="mono">Phase {r.phase}</code>
                  <span>{r.status || 'no status'}</span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** The data of the Roadmap tab is old when the collector source is down or stale (spec section 6). */
export const collectorStale = (state: HubState): boolean => !state.sources.collector.ok || state.sources.collector.stale;

interface Props {
  state: HubState;
  repo: RepoState;
  /** The roadmap the route names, or null. */
  slug: string | null;
}

export default function RoadmapTab({ state, repo, slug }: Props): JSX.Element {
  const m = deriveRoadmaps(repo);
  const stale = collectorStale(state);
  const [text, setText] = useState('');
  const search = useRef<HTMLInputElement>(null);

  // `/` focuses the search box, Escape clears it (parity P16).
  useEffect(() => {
    const on = (e: KeyboardEvent): void => {
      const t = e.target;
      const typing = t instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
      if (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        search.current?.focus();
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, []);

  const id = repoIdOf(repo);
  const staleNote = stale && (
    <p className="lane-note" data-testid="rm-stale">
      Roadmap data is old. Last good read {clockText(state.sources.collector.last_ok_at)}. The numbers below are greyed.
    </p>
  );

  let body: JSX.Element;
  if (m.mode === 'none') {
    body = (
      <div className="notice" data-testid="rm-none">
        <h2 className="rm-title">{NO_ROADMAP_TEXT}</h2>
        <p>
          Create one with <code className="cmd">{NO_ROADMAP_HINT}</code>.
        </p>
      </div>
    );
  } else if (m.mode === 'error') {
    body = (
      <div className="lane-note" data-testid="rm-errors">
        Could not read this repo: {m.repoError}
      </div>
    );
  } else if (m.mode === 'plans') {
    body = <Plans plans={m.plans} />;
  } else {
    const picked = slug ? m.roadmaps.find((r) => r.slug === slug) : opensDirectly(m) ? m.roadmaps[0] : undefined;
    if (picked) {
      const canList = m.roadmaps.length + m.errors.length > 1;
      const match = filterRoadmap(picked, text);
      body = (
        <>
          <div className="rm-searchbar">
            <label className="rm-search">
              <Search {...ICON} />
              <span className="sr-only">Search this roadmap</span>
              <input
                ref={search}
                type="search"
                data-testid="rm-search"
                placeholder="Search phases, PRs, milestones (press /)"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setText('');
                }}
              />
            </label>
            <span className="rm-match" data-testid="rm-match-count" aria-live="polite">
              {match ? `${match.count} ${match.count === 1 ? 'match' : 'matches'}` : ''}
            </span>
          </div>
          <Detail m={picked} repo={repo} crumbHref={canList ? repoTabHref(id, 'roadmap') : null} match={match} />
        </>
      );
    } else {
      body = (
        <>
          {slug && (
            <p className="lane-note" data-testid="rm-missing">
              No roadmap named {slug} in this repo.
            </p>
          )}
          <ListView repo={repo} m={m} />
        </>
      );
    }
  }

  return (
    <div className={`rm${stale ? ' stale' : ''}`} data-testid="roadmap-tab">
      {staleNote}
      {body}
    </div>
  );
}
