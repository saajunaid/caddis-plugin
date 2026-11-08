import { useState } from 'react';
import { Tooltip } from '../shell/Tooltip';
import { DONE_SHOWN, type DonePlanView } from './roadmap';

/** Unix seconds to a UTC date, `YYYY-MM-DD`. */
const dayText = (seconds: number): string => new Date(seconds * 1000).toISOString().slice(0, 10);

/** Finished plans of the repo, collapsed (plan D4, D5). The same list shows in the hub and in the Pages export. */
export function DonePlans({ plans }: { plans: DonePlanView[] }): JSX.Element | null {
  const [all, setAll] = useState(false);
  if (plans.length === 0) return null;
  const rows = all ? plans : plans.slice(0, DONE_SHOWN);
  return (
    <details className="rm-done" data-testid="rm-done">
      <summary className="rm-done-sum">
        <span className="rm-plan-title">Done plans</span>
        <span className="rm-sub">{plans.length}</span>
      </summary>
      <ul className="rm-done-list">
        {rows.map((p) => (
          <li key={p.path} className="rm-done-row" data-testid="rm-done-row">
            <Tooltip
              content={
                <>
                  <span className="mono">{p.path}</span>
                  <span>closed {p.closedAt === null ? 'date unknown' : new Date(p.closedAt * 1000).toISOString()}</span>
                  <span>
                    {p.phases} {p.phases === 1 ? 'phase' : 'phases'}
                    {p.pr ? ` · #${p.pr.number}` : ''}
                  </span>
                </>
              }
            >
              <span className="rm-done-title" tabIndex={0}>{p.title}</span>
            </Tooltip>
            <span className="rm-done-meta">
              <span className="rm-done-date">{p.closedAt === null ? 'date unknown' : dayText(p.closedAt)}</span>
              <span>
                {p.phases} {p.phases === 1 ? 'phase' : 'phases'}
              </span>
              {p.pr &&
                (p.pr.url ? (
                  <a className="rm-pr mono" data-testid="rm-done-pr" href={p.pr.url} target="_blank" rel="noreferrer noopener">
                    #{p.pr.number}
                  </a>
                ) : (
                  <span className="rm-pr mono" data-testid="rm-done-pr">
                    #{p.pr.number}
                  </span>
                ))}
            </span>
          </li>
        ))}
      </ul>
      {!all && plans.length > DONE_SHOWN && (
        <button type="button" className="btn" data-testid="rm-done-all" onClick={() => setAll(true)}>
          Show all {plans.length}
        </button>
      )}
    </details>
  );
}
