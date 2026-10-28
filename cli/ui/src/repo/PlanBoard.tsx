import {
  PLAN_COLUMNS,
  planColumns,
  planKpis,
  type PlanView,
  type Tile,
} from './roadmap';

export const CARD_TONE: Record<Tile, string> = { todo: 'todo', 'in-progress': 'prog', blocked: 'block', done: 'done', moved: 'done' };

/** The card's status line: a bare open box adds nothing, the column already says "to do". */
export const cardText = (status: string): string => status.replace(/^☐\s*/u, '').trim();

/** The KPI line of a plan: always visible, also when the board is closed. */
export function PlanKpiLine({ plan }: { plan: PlanView }): JSX.Element | null {
  if (plan.rows.length === 0) return null;
  const k = planKpis(plan);
  return (
    <span className="rm-pkpis" data-testid="rm-plan-kpis">
      <span className="rm-pkpi">
        <span className="rm-pkpi-num">
          {k.done} / {k.total}
        </span>{' '}
        done
      </span>
      <span className="rm-pbar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={k.pct} aria-label="Share of rows done">
        <span style={{ width: `${k.pct}%` }} />
      </span>
      <span className="rm-pkpi rm-pkpi-pct">{k.pct} %</span>
      <span className={`rm-pkpi${k.inProgress ? ' tone-prog' : ''}`}>
        <span className="rm-pkpi-num">{k.inProgress}</span> in progress
      </span>
      <span className={`rm-pkpi${k.blocked ? ' tone-block' : ''}`}>
        <span className="rm-pkpi-num">{k.blocked}</span> blocked
      </span>
      <span className="rm-pkpi">
        <span className="rm-pkpi-num">{k.todo}</span> to do
      </span>
    </span>
  );
}

/** One plan's Tracker as kanban columns: a card per row, in columns by state. */
export function PlanColumns({ plan }: { plan: PlanView }): JSX.Element {
  if (plan.rows.length === 0) {
    return (
      <p className="col-empty" data-testid="rm-plan-board">
        This plan has no Tracker table.
      </p>
    );
  }
  const cols = planColumns(plan);
  return (
    <div className="rm-cols rm-cols-4" data-testid="rm-plan-board">
      {PLAN_COLUMNS.map((c) => (
        <div key={c.key} data-col={c.key}>
          <h4 className="rm-list-h">
            {c.label} · {cols[c.key].length}
          </h4>
          {cols[c.key].length === 0 ? (
            <p className="col-empty">none</p>
          ) : (
            cols[c.key].map((r, i) => (
              <div key={`${r.phase}-${i}`} className={`rm-rcard rm-pcard tone-${CARD_TONE[r.state]}${r.state === 'moved' ? ' is-moved' : ''}`}>
                <strong>{r.phase}</strong>
                {cardText(r.status) ? <span className="rm-sub">{cardText(r.status)}</span> : null}
              </div>
            ))
          )}
        </div>
      ))}
    </div>
  );
}
