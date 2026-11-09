import { Check, Copy, Terminal } from 'lucide-react';
import { useState } from 'react';
import { KIND_LABEL, type InboxItem } from '../inbox/derive';
import { headline } from '../inbox/headline';
import { KindTile } from '../inbox/KindTile';
import type { InboxApi } from '../inbox/useInbox';
import { copyText } from '../shell/clipboard';
import { FirstRun } from '../shell/FirstRun';
import { ageText, anySourceDown } from '../shell/format';
import { PageHead } from '../shell/PageHead';
import { Ring, SpendBlock, type RingTone } from '../shell/Ring';
import type { HubState } from '../types';
import { deriveLive, deriveRepoCards, type RepoCard } from './cards';

const NEEDS_SHOWN = 3;
const IDLE_SHOWN = 5;

const shortAge = (iso: string | null, now: number): string | null => (iso ? ageText(iso, now).replace(/ ago$/, '') : null);

function ringTone(c: RepoCard): RingTone {
  if (c.prsOpen === 0) return 'muted';
  return c.prsPassing === c.prsOpen ? 'good' : 'prog';
}

/** One Needs you row: the kind tile, the title and one copy button (D10: the same action as the Inbox detail). */
function NeedRow({ item, primary, nowMs }: { item: InboxItem; primary: boolean; nowMs: number }): JSX.Element {
  const [copied, setCopied] = useState(false);
  const age = shortAge(item.since, nowMs);
  const label = item.kind === 'waiting' ? 'Copy session name' : 'Copy command';
  return (
    <li className="ov-need" data-testid="ov-need">
      <KindTile kind={item.kind} />
      <span className="ov-need-main">
        <span className="ov-need-title">{item.title}</span>
        <span className="ov-need-meta">
          {KIND_LABEL[item.kind]} · <span className="mono">{item.repo}</span>
          {age ? ` · ${age}` : ''}
        </span>
      </span>
      <button
        type="button"
        className={`btn ${primary ? 'btn-primary' : 'btn-ghost'}`}
        onClick={() => {
          copyText(item.cmd);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
        {copied ? 'Copied' : label}
      </button>
    </li>
  );
}

function RepoCardView({ c }: { c: RepoCard }): JSX.Element {
  return (
    <article className={`repo-card ${c.mode}`} data-testid="repo-card">
      <div className="repo-card-head">
        <span className="repo-card-id">
          <a className="repo-card-link" href={c.href}>
            {c.name}
          </a>
          <span className={`repo-card-status tone-${c.statusTone}`} data-testid="repo-card-status">
            {c.status}
          </span>
        </span>
        <Ring
          fraction={c.prsOpen > 0 ? c.prsPassing / c.prsOpen : 0}
          size={48}
          text={c.ringLabel}
          tone={ringTone(c)}
          label={c.prsOpen > 0 ? `${c.prsPassing} of ${c.prsOpen} open PRs pass required checks` : 'No open PRs'}
        />
      </div>
      <p className="repo-card-line" data-testid="repo-card-line">
        {c.line}
      </p>
      <p className="repo-card-sessions" data-testid="repo-card-sessions">
        {c.sessions}
      </p>
      {c.note && (
        <p className="lane-note repo-card-note" data-testid="repo-card-note">
          {c.note}
        </p>
      )}
      {c.github && (
        <div className="lane-note gh-fail" data-testid="gh-fail" role="status">
          GitHub access failed for {c.github.account ? `account ${c.github.account}` : 'this repo'}
          {c.github.error ? ` (${c.github.error})` : ''}. Sign in again with <code className="cmd">{c.github.command}</code>
        </div>
      )}
      <p className="repo-card-foot">{c.foot}</p>
    </article>
  );
}

/**
 * The Overview (Aurora mockup B): what needs the owner, what runs now, and one card per repo. The cards carry no
 * queue buttons: Mark hotfix, Hold and Release live on the repo Flow tab and in the Inbox detail (D4).
 */
export function Overview({ state, nowMs, api }: { state: HubState; nowMs: number; api: InboxApi }): JSX.Element {
  const items = api.model.items;
  const live = deriveLive(state);
  const cards = deriveRepoCards(state, nowMs);
  const idle = live.other.slice(0, IDLE_SHOWN);

  return (
    <>
      <PageHead page="Overview" head={headline(state, items.length, nowMs)} stale={anySourceDown(state)} />
      {state.repos.length === 0 && <FirstRun />}
      <div className="ov-top">
        <section className="ov-needs glass-panel" aria-label="Needs you" data-testid="ov-needs">
          <div className="ov-panel-head">
            <h2>Needs you</h2>
            <a className="ov-all" href="#/inbox">
              All {items.length} items
            </a>
          </div>
          {items.length === 0 ? (
            <p className="ov-empty">Nothing needs you.</p>
          ) : (
            <ul className="ov-need-list">
              {items.slice(0, NEEDS_SHOWN).map((item, i) => (
                <NeedRow key={item.id} item={item} primary={i === 0} nowMs={nowMs} />
              ))}
            </ul>
          )}
        </section>
        <section className="ov-live glass-panel" aria-label="Live now" data-testid="ov-live">
          <div className="ov-panel-head">
            <h2>Live now</h2>
          </div>
          {live.busy.length === 0 ? (
            <p className="ov-empty">No agent is working.</p>
          ) : (
            live.busy.map((r) => (
              <div key={r.key} className="live-row" data-testid="live-session">
                <span className="live-mark" aria-hidden="true">
                  <span className="live-orb" />
                  <span className="live-core">
                    <Terminal size={20} />
                  </span>
                </span>
                <span className="live-text">
                  <span className="live-name">{r.name}</span>
                  <span className="live-where">Working in {r.repo}</span>
                </span>
              </div>
            ))
          )}
          {idle.length > 0 && (
            <ul className="live-idle">
              {idle.map((r) => (
                <li key={r.key} data-testid="idle-session">
                  <span className="live-idle-dot" aria-hidden="true" />
                  <span className="live-idle-name">{r.name}</span>
                  <span className="mono live-idle-repo">{r.repo}</span>
                </li>
              ))}
              {live.other.length > IDLE_SHOWN && <li className="live-more">+{live.other.length - IDLE_SHOWN} more</li>}
            </ul>
          )}
          <div className="ov-spend">
            <SpendBlock slot={state.spend} size={44} />
          </div>
        </section>
      </div>
      <section className="ov-repos" aria-label="Repos">
        <div className="ov-repos-head">
          <h2>Repos</h2>
          <span>{cards.length} watched</span>
        </div>
        <div className="repo-cards" data-testid="repo-cards">
          {cards.map((c) => (
            <RepoCardView key={c.id} c={c} />
          ))}
        </div>
      </section>
    </>
  );
}
