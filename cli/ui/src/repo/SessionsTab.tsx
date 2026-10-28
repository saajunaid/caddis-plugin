import { Copy } from 'lucide-react';
import { useState } from 'react';
import { ageText } from '../shell/format';
import type { HubState, RepoState } from '../types';
import { repoSessions } from './sessions';

/** Copy text to the clipboard. Local only (spec 7). A failure is not an error: the name is on the page. */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

const WAIT_LABEL = { owner: 'you', peer: 'a peer session' } as const;

/** The Sessions tab (R50): this repo's sessions, waiting first. */
export function Sessions({ state, repo, nowMs }: { state: HubState; repo: RepoState; nowMs: number }): JSX.Element {
  const m = repoSessions(state, repo);
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async (key: string, name: string): Promise<void> => {
    if (await copyText(name)) {
      setCopied(key);
      window.setTimeout(() => setCopied((c) => (c === key ? null : c)), 2000);
    }
  };
  return (
    <div className="flow" data-testid="sessions">
      {m.error && (
        <div className="lane-note" data-testid="sessions-error">
          {m.unknown ? 'Sessions unknown: ' : 'The last sessions read failed: '}
          {m.error}
        </div>
      )}
      {m.unknown ? (
        <p className="col-empty">The hub could not read the session list. PRs and deploys are on the Flow tab.</p>
      ) : m.rows.length === 0 ? (
        <p className="col-empty" data-testid="sessions-empty">
          No sessions running. PRs and deploys are on the Flow tab.
        </p>
      ) : (
        <ul className="flow-list" data-testid="sessions-table" aria-label="Sessions of this repo">
          {m.rows.map((s) => (
            <li key={s.key} className="flow-row" data-testid="session-row">
              <div className="flow-row-head">
                <span className="flow-title mono">{s.name}</span>
                {s.agent && (
                  <span className="chip tone-muted" data-testid="session-agent">
                    {s.agent}
                  </span>
                )}
                <span className={`chip tone-${s.status === 'waiting' ? 'warn' : s.status === 'busy' || s.status === 'working' ? 'good' : 'muted'}`}>{s.status}</span>
                {s.copyWarning && (
                  <span className="chip tone-bad" data-testid="session-copies">
                    {s.copyWarning}
                  </span>
                )}
                <button type="button" className="btn btn-act" onClick={() => void copy(s.key, s.name)} aria-label={`Copy session name ${s.name}`}>
                  <Copy size={14} aria-hidden="true" />
                  {copied === s.key ? 'Copied' : 'Copy name'}
                </button>
              </div>
              <span className="flow-why">
                {s.kind}
                {s.waitingFor ? ` · waiting for ${s.waitingClass ? WAIT_LABEL[s.waitingClass] : 'an answer'}: ${s.waitingFor}` : ''}
                {s.since ? ` · since ${ageText(s.since, nowMs)}` : ''}
              </span>
              {s.copyWarning && <span className="flow-why tone-bad">The same session runs in {s.copies} windows. Close the extra copy.</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
