import { ArrowRightLeft, Circle, CircleCheck, Loader, OctagonAlert } from 'lucide-react';
import { Tooltip } from '../shell/Tooltip';
import { PhasePrs, Pill } from './PhasePanel';
import {
  phaseMeta,
  TILE_LABEL,
  type Match,
  type MilestoneView,
  type PhaseView,
  type RoadmapModel,
  type Tile,
} from './roadmap';

export const TILE_ICON: Record<Tile, typeof Circle> = {
  todo: Circle,
  'in-progress': Loader,
  done: CircleCheck,
  moved: ArrowRightLeft,
  blocked: OctagonAlert,
};
export const ICON = { size: 14, 'aria-hidden': true } as const;

export function TileIcon({ tile }: { tile: Tile }): JSX.Element {
  const Icon = TILE_ICON[tile];
  return <Icon {...ICON} />;
}

/** The hover text of a phase tile: only what the phase already holds. */
export function PhaseTip({ p }: { p: PhaseView }): JSX.Element {
  const meta = phaseMeta(p);
  return (
    <>
      <strong>
        {p.ref} {p.name}
      </strong>
      <span>
        {TILE_LABEL[p.tile]} · {p.tracker || p.stage}
      </span>
      {p.prs.length > 0 && <span>{p.prs.map((pr) => `#${pr.number}`).join(' ')}</span>}
      {meta && <span>{meta}</span>}
      {p.highRisk && <span>high risk</span>}
    </>
  );
}

export const gateCountText = (n: number): string => `${n} ${n === 1 ? 'gate' : 'gates'}`;

/** The milestone line: who runs it, the target, and what it waits for (left out when nothing). */
export function milestoneMeta(ms: Pick<MilestoneView, 'owner' | 'target' | 'depends'>): string {
  return [`run by ${ms.owner}`, ms.target ? `target ${ms.target}` : '', ms.depends.length ? `after ${ms.depends.join(', ')}` : '']
    .filter(Boolean)
    .join(' · ');
}

export function Bar({ done, total }: { done: number; total: number }): JSX.Element {
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

/** Jump to a milestone: open it and scroll to it. Hash links stay free for the router. */
export function openMilestone(slug: string, id: string): void {
  const el = document.getElementById(`ms-${slug}-${id}`);
  if (el instanceof HTMLDetailsElement) el.open = true;
  el?.scrollIntoView({ block: 'start' });
}

export function Timeline({ m, match, onOpen }: { m: RoadmapModel; match: Match | null; onOpen: (ref: string, el: HTMLElement) => void }): JSX.Element {
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
              {ms.blockers.length > 0 && <span className="rm-gate-count">{gateCountText(ms.blockers.length)}</span>}
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
                    <Tooltip key={p.ref} content={<PhaseTip p={p} />}>
                      <button type="button" className="rm-tile" data-state={p.tile} data-risk={p.highRisk ? 'high' : undefined} onClick={(e) => onOpen(p.ref, e.currentTarget)}>
                        <TileIcon tile={p.tile} />
                        {m.kind !== 'plan' && <b className="mono">{p.num}</b>}
                        <span>{p.name}</span>
                        <span className="sr-only">{TILE_LABEL[p.tile]}</span>
                        {p.highRisk && <i className="rm-risk" aria-label="high risk" />}
                      </button>
                    </Tooltip>
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
                  <Tooltip key={i} content={`${b.type}: ${b.reason}`}>
                    <div className="rm-gate-note" tabIndex={0}>
                      {b.type}: {b.reason.length > 60 ? `${b.reason.slice(0, 60)}…` : b.reason}
                    </div>
                  </Tooltip>
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
              <Tooltip key={p.ref} content={<PhaseTip p={p} />}>
                <button type="button" className="rm-tile" data-state={p.tile} data-risk={p.highRisk ? 'high' : undefined} onClick={(e) => onOpen(p.ref, e.currentTarget)}>
                  <TileIcon tile={p.tile} />
                  {m.kind !== 'plan' && (
                    <b className="mono">
                      {p.plan} {p.num}
                    </b>
                  )}
                  <span>{p.name}</span>
                  <span className="sr-only">{TILE_LABEL[p.tile]}</span>
                  {p.highRisk && <i className="rm-risk" aria-label="high risk" />}
                </button>
              </Tooltip>
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

export function Milestones({ m, match, onOpen }: { m: RoadmapModel; match: Match | null; onOpen: (ref: string, el: HTMLElement) => void }): JSX.Element {
  return (
    <section className="rm-section" data-testid="rm-milestones" aria-label="Milestones and phases">
      <h3 className="flow-h">Milestones and phases</h3>
      {m.milestones
        .filter((ms) => !match || match.milestones.has(ms.id))
        .map((ms) => (
          <details key={`${ms.id}-${match ? 'q' : 'n'}`} className="rm-ms" id={`ms-${m.slug}-${ms.id}`} open={match ? true : undefined}>
            <summary>
              <strong>{ms.id}</strong> <Pill status={ms.status} />
              {m.kind !== 'plan' && (
                <span className="rm-sub">
                  {milestoneMeta(ms)}
                </span>
              )}
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
                        <button type="button" className="flow-title rm-open" onClick={(e) => onOpen(p.ref, e.currentTarget)}>{p.name}</button>
                        <PhasePrs phase={p} />
                      </div>
                      <span className="flow-why">
                        {phaseMeta(p) || 'no model, lane or risk recorded'}
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
