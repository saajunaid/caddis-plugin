import { useState } from 'react';
import { ActionButtons } from '../actions/ActionButtons';
import { ownerDisabledReason, ownerSpecs, queueSpecs, requestText, requestTone } from '../actions/model';
import { RecommendationBlock } from '../actions/Recommendation';
import type { ActApi } from '../actions/useActions';
import { repoLabel } from '../inbox/derive';
import { ageText } from '../shell/format';
import type { HubState, RepoState } from '../types';
import { deriveFlow, type FlowItem } from './flow';

type Tab = 'flow' | 'roadmap' | 'sessions';
const TABS: { id: Tab; label: string }[] = [
  { id: 'flow', label: 'Flow' },
  { id: 'roadmap', label: 'Roadmap' },
  { id: 'sessions', label: 'Sessions' },
];

const STATE_TONE: Record<string, string> = { ready: 'good', merging: 'good', blocked: 'bad', held: 'warn', ci: 'muted', waiting: 'muted' };

function QueueRow({ repo, item, grey, act }: { repo: RepoState; item: FlowItem; grey: boolean; act: ActApi }): JSX.Element {
  return (
    <li className={`flow-row${grey ? ' grey' : ''}`} data-testid="queue-item">
      <div className="flow-row-head">
        <span className="flow-pos mono">{item.position}</span>
        <span className="flow-title">
          #{item.pr} {item.title}
        </span>
      </div>
      <div className="flow-flags">
        <span className={`chip tone-${STATE_TONE[item.state] ?? 'muted'}`}>{item.state}</span>
        {item.merging && <span className="chip tone-good">merging now</span>}
        {item.hotfix && (
          <span className="chip tone-warn" data-testid="flag-hotfix">
            hotfix
          </span>
        )}
        {item.held && (
          <span className="chip tone-warn" data-testid="flag-held">
            held
          </span>
        )}
      </div>
      {item.whyWaiting && <span className="flow-why">{item.whyWaiting}</span>}
      {item.waitsOn.length > 0 && (
        <span className="flow-why">Waits on {item.waitsOn.map((w) => `${w.repo.replace('__', '/')}#${w.pr}`).join(', ')}</span>
      )}
      <ActionButtons repo={repo} specs={queueSpecs(repo, { pr: item.pr, headSha: item.headSha, hotfix: item.hotfix, held: item.held })} act={act} />
    </li>
  );
}

function Flow({ state, repo, nowMs, act }: { state: HubState; repo: RepoState; nowMs: number; act: ActApi }): JSX.Element {
  const f = deriveFlow(state, repo);
  return (
    <div className="flow" data-testid="flow">
      <div className={`lane-note flow-status ${f.mode}`} data-testid="flow-status">
        {f.statusText}
      </div>

      {f.owner.length > 0 && (
        <section className="flow-section" aria-label="Owner approvals">
          <h2 className="flow-h">Needs your approval · {f.owner.length}</h2>
          <ul className="flow-list">
            {f.owner.map((o) => (
              <li key={o.id} className="flow-row" data-testid="owner-item">
                <span className="flow-title">
                  {o.pr !== null ? `#${o.pr} ` : ''}
                  {o.what}
                </span>
                <RecommendationBlock item={o} />
                <ActionButtons repo={repo} specs={ownerSpecs(repo, o)} act={act} reason={ownerDisabledReason(repo, o)} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="flow-section" aria-label="Merge queue">
        <h2 className="flow-h">
          Merge queue · {f.queue.length}
          {f.grey ? ' · last known' : ''}
        </h2>
        {f.mode === 'none' ? (
          <p className="col-empty">No queue: this repo has no coordinator.</p>
        ) : f.queue.length === 0 ? (
          <p className="col-empty">The queue is empty.</p>
        ) : (
          <ol className="flow-list">
            {f.queue.map((q) => (
              <QueueRow key={q.pr} repo={repo} item={q} grey={f.grey} act={act} />
            ))}
          </ol>
        )}
      </section>

      <section className="flow-section" aria-label="Deploy checks">
        <h2 className="flow-h">Deploy checks</h2>
        {f.deploys.length === 0 ? (
          <p className="col-empty">No deploy check recorded.</p>
        ) : (
          <ul className="flow-list">
            {f.deploys.map((d) => (
              <li key={`${d.pr}-${d.mergeSha}`} className="flow-row" data-testid="deploy-check">
                <div className="flow-row-head">
                  <span className="flow-title">
                    #{d.pr} <span className="mono">{d.mergeSha}</span>
                  </span>
                  <span className={`chip tone-${d.health === 'ok' ? 'good' : d.health === 'failed' ? 'bad' : 'muted'}`}>health {d.health}</span>
                </div>
                {d.checks && (
                  <div className="flow-flags" data-testid="deploy-marks">
                    {d.checks.map((c) => (
                      <span key={c.name} className={`chip tone-${c.mark === 'pass' ? 'good' : c.mark === 'fail' ? 'bad' : 'muted'}`}>
                        {c.name} {c.mark}
                      </span>
                    ))}
                  </div>
                )}
                <span className="flow-why">
                  {d.run !== null ? `run ${d.run} · ` : ''}
                  {ageText(d.at, nowMs)}
                  {d.reason ? ` · ${d.reason}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {f.unqueued.length > 0 && (
        <section className="flow-section" aria-label="Open PRs not in the queue">
          <h2 className="flow-h">Open PRs not in the queue · {f.unqueued.length}</h2>
          <ul className="flow-list">
            {f.unqueued.map((p) => (
              <li key={p.number} className="flow-row" data-testid="unqueued-pr">
                <span className="flow-title">
                  #{p.number} {p.title}
                </span>
                <span className={`flow-why tone-${p.requiredState === 'fail' ? 'bad' : p.requiredState === 'pass' ? 'good' : 'muted'}`}>
                  required checks {p.requiredState}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {f.requests.length > 0 && (
        <section className="flow-section" aria-label="Your requests">
          <h2 className="flow-h">Your requests</h2>
          <ul className="flow-list">
            {f.requests.slice(0, 10).map((r) => (
              <li key={r.id} className="flow-row" data-testid="request-log">
                <span className={`tone-${requestTone(r.status)}`}>{requestText(r)}</span>
                <span className="flow-why">
                  {r.pr !== null ? `PR #${r.pr}` : r.what} · {ageText(r.created_at, nowMs)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function RepoPage({ state, repo, nowMs, act }: { state: HubState; repo: RepoState; nowMs: number; act: ActApi }): JSX.Element {
  const [tab, setTab] = useState<Tab>('flow');
  return (
    <>
      <div className="page-header">
        <h1 className="page-title">{repoLabel(repo)}</h1>
        <span className="page-subtitle">{repo.name}</span>
      </div>
      <div className="repo-tabs" role="tablist" aria-label="Repo views">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`folder-btn${tab === t.id ? ' sel' : ''}`}
            onClick={() => setTab(t.id)}
            data-testid={`tab-${t.id}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'flow' ? (
        <Flow state={state} repo={repo} nowMs={nowMs} act={act} />
      ) : (
        <div className="notice">
          <p>The {tab === 'roadmap' ? 'Roadmap' : 'Sessions'} tab arrives in H4.</p>
        </div>
      )}
    </>
  );
}
