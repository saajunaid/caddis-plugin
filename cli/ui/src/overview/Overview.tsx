import { ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { browserStore, FOLDED_KEY, readJson, writeJson } from '../inbox/store';
import { FirstRun } from '../shell/FirstRun';
import { anySourceDown } from '../shell/format';
import { Tiles } from '../inbox/Tiles';
import type { InboxApi } from '../inbox/useInbox';
import type { HubState } from '../types';
import { deriveLanes, type Lane } from './lanes';

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

export function Overview({ state, nowMs, api }: { state: HubState; nowMs: number; api: InboxApi }): JSX.Element {
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
          return (
            <section key={lane.id} className={`lane ${lane.mode}`} data-testid="lane" aria-label={lane.name}>
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
                      <div key={c.id} className="lane-col" data-testid={`col-${c.id}`}>
                        <span className="col-title">
                          {c.title} · {c.cards.length}
                        </span>
                        {c.cards.map((k) => (
                          <div key={k.key} className={`card${k.grey ? ' grey' : ''}`}>
                            <span className="card-title">{k.title}</span>
                            <span className={`card-sub tone-${k.tone}`}>{k.sub}</span>
                          </div>
                        ))}
                        {c.cards.length === 0 && <span className="col-empty">{c.emptyText}</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </>
  );
}
