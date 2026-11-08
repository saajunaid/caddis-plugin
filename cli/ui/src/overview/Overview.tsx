import { ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { ActionButtons } from '../actions/ActionButtons';
import { queueSpecs } from '../actions/model';
import type { ActApi } from '../actions/useActions';
import { samePath } from '../inbox/derive';
import { browserStore, FOLDED_KEY, readJson, writeJson } from '../inbox/store';
import { FirstRun } from '../shell/FirstRun';
import { repoHref, repoId } from '../shell/route';
import { Tooltip } from '../shell/Tooltip';
import { anySourceDown } from '../shell/format';
import { Tiles } from '../inbox/Tiles';
import type { InboxApi } from '../inbox/useInbox';
import type { HubState } from '../types';
import { deriveLanes, type Card, type Column, type Lane } from './lanes';

const TONE_TIP: Record<Lane['tone'], string> = {
  ok: 'ok: nothing needs attention',
  attention: 'attention: something waits on an answer',
  blocked: 'blocked: a merge or check is failing',
  idle: 'idle: no sessions or PRs are active',
};

/** The hover text of a lane card: the full text of the card and its queue data. */
function cardTip(k: Card): JSX.Element {
  const q = k.queue;
  return (
    <>
      <strong>{k.title}</strong>
      <span>{k.sub}</span>
      {q && (
        <span className="mono">
          #{q.pr} · head {q.headSha.slice(0, 7)}
          {q.hotfix ? ' · hotfix' : ''}
          {q.held ? ' · held' : ''}
        </span>
      )}
    </>
  );
}

/** The generic empty text of a column (lanes.ts). A column with its own empty text (no coordinator, sessions unknown) keeps it. */
const NONE_TEXT = 'None';
const isBlank = (c: Column): boolean => c.cards.length === 0 && c.emptyText === NONE_TEXT;

const DOT: Record<Lane['tone'], string> = {
  ok: 'var(--green)',
  attention: 'var(--mk-warn)',
  blocked: 'var(--mk-bad)',
  idle: 'var(--text-dim)',
};

function loadFolded(): Record<string, boolean> {
  const raw = readJson(FOLDED_KEY, browserStore());
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, boolean>) : {};
}

export function Overview({ state, nowMs, api, act }: { state: HubState; nowMs: number; api: InboxApi; act: ActApi }): JSX.Element {
  const [folded, setFolded] = useState<Record<string, boolean>>(() => loadFolded());
  const lanes = deriveLanes(state, nowMs);
  const toggle = (id: string): void => {
    setFolded((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      writeJson(FOLDED_KEY, next, browserStore());
      return next;
    });
  };

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">Overview</h1>
        <span className="page-subtitle">
          {state.repos.length} repos · {state.sessions.length} sessions
        </span>
      </div>
      {state.repos.length === 0 && <FirstRun />}
      <Tiles tiles={api.model.tiles} stale={anySourceDown(state)} />
      <div className={`lanes${anySourceDown(state) ? ' stale' : ''}`} data-testid="lanes">
        {lanes.map((lane) => {
          const open = !folded[lane.id];
          const repo = state.repos.find((r) => samePath(r.path, lane.id));
          return (
            <section key={lane.id} className={`lane ${lane.mode}`} data-testid="lane" aria-label={lane.name}>
              <div className="lane-headrow">
              <Tooltip content={TONE_TIP[lane.tone]}>
              <button type="button" className="lane-head" aria-expanded={open} onClick={() => toggle(lane.id)}>
                <span
                  aria-hidden="true"
                  style={{ width: 9, height: 9, borderRadius: '50%', background: DOT[lane.tone], flexShrink: 0 }}
                />
                <span className="lane-name">{lane.name}</span>
                <span className="lane-summary" data-testid="lane-summary">
                  {lane.summary}
                </span>
                <ChevronDown
                  className="chev"
                  size={18}
                  aria-hidden="true"
                  style={{ transform: open ? 'rotate(180deg)' : 'none' }}
                />
              </button>
              </Tooltip>
              {repo && (
                <a className="lane-open" href={repoHref(repoId(repo))}>
                  Open repo
                </a>
              )}
              </div>
              {open && (
                <div className="lane-body">
                  {lane.github && (
                    <div className="lane-note gh-fail" data-testid="gh-fail" role="status">
                      GitHub access failed for {lane.github.account ? `account ${lane.github.account}` : 'this repo'}
                      {lane.github.error ? ` (${lane.github.error})` : ''}. Sign in again with{' '}
                      <code className="cmd">{lane.github.command}</code>
                    </div>
                  )}
                  {lane.note && (
                    <div className="lane-note" data-testid="lane-note">
                      {lane.note}
                    </div>
                  )}
                  <div className="lane-cols">
                    {lane.columns.map((c) => (
                      <div key={c.id} className={`lane-col${isBlank(c) ? ' empty' : ''}`} data-testid={`col-${c.id}`}>
                        <span className="col-title">
                          {c.title} · {c.cards.length}
                        </span>
                        {c.cards.map((k) => (
                          <Tooltip key={k.key} content={cardTip(k)}>
                            <div className={`card${k.grey ? ' grey' : ''}`} data-testid="lane-card" tabIndex={0}>
                              <span className="card-title">{k.title}</span>
                              <span className={`card-sub tone-${k.tone}`}>{k.sub}</span>
                              {repo && k.queue && <ActionButtons repo={repo} specs={queueSpecs(repo, k.queue)} act={act} compact />}
                            </div>
                          </Tooltip>
                        ))}
                        {c.cards.length === 0 && !isBlank(c) && <span className="col-empty">{c.emptyText}</span>}
                      </div>
                    ))}
                  </div>
                  {lane.columns.some(isBlank) && (
                    <span className="lane-empty-line" data-testid="lane-empty-line">
                      Empty: {lane.columns.filter(isBlank).map((c) => c.title).join(', ')}
                    </span>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </>
  );
}
