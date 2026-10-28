import { repoLabel } from '../inbox/derive';
import { localTime } from '../shell/time';
import type { RepoState } from '../types';
import { usePhasePanel, useRoadmapView, ViewSwitch } from './detailParts';
import { Pill } from './PhasePanel';
import type { Match, MilestoneView, PlanView, RoadmapModel, RoadmapView } from './roadmap';
import type { Variant } from './RoadmapTab';
import { Bar, Milestones, openMilestone, Timeline } from './RoadmapTimeline';

export function RoadmapDetail({
  m,
  repo,
  crumbHref,
  match,
  variant,
  initialView,
  plans,
}: {
  m: RoadmapModel;
  repo: RepoState;
  crumbHref: string | null;
  match: Match | null;
  variant: Variant;
  initialView?: RoadmapView;
  plans?: PlanView[];
}): JSX.Element {
  const [view, chooseView] = useRoadmapView(initialView);
  const { open, panel } = usePhasePanel({ m, pool: plans ?? [], repo, variant });
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

      <ViewSwitch view={view} choose={chooseView} />

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

      {view === 'timeline' ? (
        <Timeline m={m} match={match} onOpen={open} />
      ) : (
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
      )}

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

      <Milestones m={m} match={match} onOpen={open} />

      {variant === 'hub' && (
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
      )}
      {panel}
    </div>
  );
}
