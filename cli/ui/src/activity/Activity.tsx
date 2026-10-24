import { ExternalLink } from 'lucide-react';
import { useMemo, useState } from 'react';
import { localTime } from '../shell/time';
import { repoTabHref } from '../shell/route';
import type { HubState } from '../types';
import { deriveActivity, filterActivity, KIND_LABEL, KINDS, PAGE_SIZE, repoIdOf, type Kind } from './derive';

/** The Activity page (spec section 5 page 4): newest first, filter by repo and kind, local time with the zone. */
export default function Activity({ state }: { state: HubState }): JSX.Element {
  const events = useMemo(() => deriveActivity(state), [state]);
  const [repo, setRepo] = useState<string | null>(null);
  const [kinds, setKinds] = useState<ReadonlySet<Kind>>(new Set());
  const [shown, setShown] = useState(PAGE_SIZE);

  const rows = filterActivity(events, { repo, kinds });
  const toggle = (k: Kind): void => {
    const next = new Set(kinds);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setKinds(next);
    setShown(PAGE_SIZE);
  };
  const stale = !state.sources.github.ok || state.sources.github.stale;

  return (
    <div className="flow" data-testid="activity">
      <div className="page-header">
        <h1 className="page-title">Activity</h1>
        <span className="page-subtitle">{rows.length} events, newest first</span>
      </div>
      {stale && (
        <p className="lane-note" data-testid="activity-stale">
          GitHub data is old, so merges and deploys may be missing the newest events.
        </p>
      )}
      <div className="act-filters" role="group" aria-label="Filters">
        <label>
          <span className="sr-only">Repo</span>
          <select
            data-testid="activity-repo"
            value={repo ?? ''}
            onChange={(e) => {
              setRepo(e.target.value || null);
              setShown(PAGE_SIZE);
            }}
          >
            <option value="">All repos</option>
            {state.repos.map((r) => (
              <option key={repoIdOf(r)} value={repoIdOf(r)}>
                {r.github?.repo ?? r.name}
              </option>
            ))}
          </select>
        </label>
        <div className="act-kinds" role="group" aria-label="Kinds">
          {KINDS.map((k) => (
            <button key={k} type="button" className="act-kind" aria-pressed={kinds.has(k)} data-testid={`kind-${k}`} onClick={() => toggle(k)}>
              {KIND_LABEL[k]}
            </button>
          ))}
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="col-empty" data-testid="activity-empty">
          {events.length === 0 ? 'No activity yet. Merges, deploys and your actions show here.' : 'No event matches these filters.'}
        </p>
      ) : (
        <ul className="flow-list" aria-label="Events">
          {rows.slice(0, shown).map((e) => (
            <li key={e.id} className="flow-row" data-testid="activity-item" data-kind={e.kind}>
              <div className="flow-row-head">
                <span className="act-kindtag">{KIND_LABEL[e.kind]}</span>
                <span className={`flow-title tone-${e.tone}`}>{e.text}</span>
              </div>
              {e.detail && <span className="flow-why">{e.detail}</span>}
              <span className="act-time">
                <time dateTime={e.at}>{localTime(e.at)}</time> ·{' '}
                <a href={repoTabHref(e.repo, 'flow')}>{e.repoLabel}</a>
                {e.prUrl && (
                  <>
                    {' · '}
                    <a href={e.prUrl} target="_blank" rel="noreferrer noopener" data-testid="activity-pr">
                      #{e.pr} <ExternalLink size={12} aria-hidden="true" />
                    </a>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {rows.length > shown && (
        <button type="button" className="btn" data-testid="activity-more" onClick={() => setShown(shown + PAGE_SIZE)}>
          Show more ({rows.length - shown} left)
        </button>
      )}
    </div>
  );
}
