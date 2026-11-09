import { ArrowLeft, Bell, Check, Copy } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ActionButtons } from '../actions/ActionButtons';
import { RecommendationBlock } from '../actions/Recommendation';
import { ownerDisabledReason, ownerSpecs, queueSpecs, type ActionSpec } from '../actions/model';
import type { ActApi } from '../actions/useActions';
import { copyText } from '../shell/clipboard';
import { ageText, anySourceDown } from '../shell/format';
import { inboxKey, isTyping, moveIndex } from '../shell/keys';
import { PageHead } from '../shell/PageHead';
import { Tooltip } from '../shell/Tooltip';
import { localTime } from '../shell/time';
import type { HubState, RepoState } from '../types';
import { KIND_LABEL, samePath, type Folder, type InboxItem } from './derive';
import { FirstRun } from '../shell/FirstRun';
import { headline } from './headline';
import { KindTile } from './KindTile';
import { Strips } from './Strips';
import type { InboxApi } from './useInbox';

const FOLDERS: { id: Folder; label: string }[] = [
  { id: 'needs', label: 'Needs you' },
  { id: 'approvals', label: 'Approvals' },
  { id: 'blocked', label: 'Blocked' },
  { id: 'resolved', label: 'Resolved' },
];

/** A relative time that shows the absolute local time, with the zone, on hover. */
function Age({ iso, nowMs, focusable = false }: { iso: string | null; nowMs: number; focusable?: boolean }): JSX.Element {
  const text = shortAge(iso, nowMs);
  if (!iso) return <>{text}</>;
  return (
    <Tooltip content={localTime(iso)}>
      <time dateTime={iso} tabIndex={focusable ? 0 : undefined}>
        {text}
      </time>
    </Tooltip>
  );
}

const shortAge = (iso: string | null, now: number): string => (iso ? ageText(iso, now).replace(/ ago$/, '') : 'unknown');

interface Row {
  item: InboxItem;
  resolved: boolean;
  /** ISO time shown as "since". */
  since: string | null;
}

/** The v1 buttons of an Inbox item: Approve / Decline for an owner item, Hotfix / Hold for a queued PR. */
function specsFor(repo: RepoState | undefined, item: InboxItem): ActionSpec[] {
  if (!repo) return [];
  if (item.owner) return ownerSpecs(repo, item.owner);
  if (item.queue) return queueSpecs(repo, item.queue);
  return [];
}

export function Inbox({
  state,
  nowMs,
  api,
  act,
  item = null,
}: {
  state: HubState;
  nowMs: number;
  api: InboxApi;
  act: ActApi;
  /** The id from `#/inbox/<id>` (a palette link): select that item once. */
  item?: string | null;
}): JSX.Element {
  const [folder, setFolder] = useState<Folder>('needs');
  const [selId, setSelId] = useState<string | null>(null);
  const [detail, setDetail] = useState(false);
  const [copied, setCopied] = useState(false);
  const [missing, setMissing] = useState(false);
  const appliedItem = useRef<string | null>(null);
  const scrollTo = useRef<string | null>(null);
  const rowEls = useRef(new Map<string, HTMLButtonElement>());
  const { model, resolved, read } = api;

  const counts: Record<Folder, number> = {
    needs: model.items.filter((i) => i.folder === 'needs').length,
    approvals: model.items.filter((i) => i.folder === 'approvals').length,
    blocked: model.items.filter((i) => i.folder === 'blocked').length,
    resolved: resolved.length,
  };
  const rows: Row[] =
    folder === 'resolved'
      ? resolved.map((r) => ({ item: r.item, resolved: true, since: new Date(r.resolvedAt).toISOString() }))
      : model.items.filter((i) => i.folder === folder).map((i) => ({ item: i, resolved: false, since: i.since }));
  const sel = rows.find((r) => r.item.id === selId) ?? rows[0] ?? null;

  const pickFolder = (f: Folder): void => {
    setFolder(f);
    setSelId(null);
    setDetail(false);
    setMissing(false);
  };
  const pickItem = (r: Row): void => {
    setMissing(false);
    setSelId(r.item.id);
    setDetail(true);
    if (!r.resolved) api.markRead(r.item.id);
  };
  const copySel = (r: Row): void => {
    copyText(r.item.cmd);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  // A route item (from the palette) is applied once per distinct id, not on every poll.
  useEffect(() => {
    if (!item) {
      appliedItem.current = null;
      setMissing(false);
      return;
    }
    if (appliedItem.current === item) return;
    appliedItem.current = item;
    const open = model.items.find((i) => i.id === item);
    const done = open ? undefined : resolved.find((r) => r.item.id === item);
    if (!open && !done) {
      setMissing(true);
      return;
    }
    setMissing(false);
    setFolder(open ? open.folder : 'resolved');
    setSelId(item);
    setDetail(true);
    if (open) api.markRead(item);
    scrollTo.current = item;
  }, [item, model.items, resolved, api.markRead]);
  // The row exists only after the folder switch has rendered.
  useEffect(() => {
    const id = scrollTo.current;
    const el = id ? rowEls.current.get(id) : undefined;
    if (!id || !el) return;
    scrollTo.current = null;
    el.scrollIntoView?.({ block: 'nearest' });
  });

  // The key listener is added once; it reads the rows of the last render through this ref.
  const live = useRef({ rows, sel, pickItem, copySel });
  live.current = { rows, sel, pickItem, copySel };
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const t = e.target;
      const onControl = t instanceof HTMLButtonElement || t instanceof HTMLAnchorElement;
      const action = inboxKey(e.key, { ctrl: e.ctrlKey, meta: e.metaKey, alt: e.altKey }, isTyping(t), onControl);
      const { rows: list, sel: cur, pickItem: pick, copySel: copy } = live.current;
      if (!action || !cur) return;
      if (action === 'next' || action === 'prev') {
        const at = moveIndex(action, list.findIndex((r) => r.item.id === cur.item.id), list.length);
        const to = list[at];
        if (!to) return;
        setSelId(to.item.id);
        rowEls.current.get(to.item.id)?.scrollIntoView({ block: 'nearest' });
      } else if (action === 'open') {
        pick(cur);
      } else {
        copy(cur);
      }
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <>
      <PageHead page="Inbox" head={headline(state, model.items.length, nowMs)} stale={anySourceDown(state)}>
        <div className="pill-group" role="tablist" aria-label="Folders">
          {FOLDERS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={folder === id}
              className={`folder-btn pill${folder === id ? ' sel' : ''}`}
              onClick={() => pickFolder(id)}
              data-testid={`folder-${id}`}
            >
              {label}
              <strong className="pill-count">{counts[id]}</strong>
            </button>
          ))}
        </div>
      </PageHead>
      {state.repos.length === 0 && <FirstRun />}
      {api.notify.supported && (
        <div className="notify-row">
          <button type="button" className="btn" onClick={api.notify.enable} disabled={api.notify.enabled}>
            <Bell size={16} aria-hidden="true" />
            {api.notify.enabled ? 'Notifications on' : 'Notify me'}
          </button>
          <span>
            {api.notify.enabled ? 'One browser notification per new item.' : 'Opt in to a browser notification for each new item.'}
          </span>
        </div>
      )}
      <div className={`mailbox${detail && sel ? ' show-detail' : ''}`}>
        <div className="mailbox-list" data-testid="inbox-list">
          {missing && (
            <div className="list-notice" role="status" data-testid="inbox-notice">
              That item is no longer in the Inbox.
            </div>
          )}
          {rows.map((r) => {
            const unread = !r.resolved && !read.has(r.item.id);
            const on = sel?.item.id === r.item.id;
            return (
              <button
                key={r.item.id}
                ref={(el) => {
                  if (el) rowEls.current.set(r.item.id, el);
                  else rowEls.current.delete(r.item.id);
                }}
                type="button"
                className={`item-btn${on ? ' sel' : ''}`}
                aria-current={on ? 'true' : undefined}
                onClick={() => pickItem(r)}
                data-testid="inbox-item"
              >
                <span className={`unread-dot${unread ? ' on' : ''}`} role="img" aria-label={unread ? 'Unread' : 'Read'} />
                <KindTile kind={r.resolved ? 'resolved' : r.item.kind} />
                <span className="item-main">
                  <span className="item-title">{r.item.title}</span>
                  <span className="item-meta">
                    <span>{r.resolved ? 'Resolved' : KIND_LABEL[r.item.kind]}</span>
                    <span aria-hidden="true">·</span>
                    <span className="mono">{r.item.repo}</span>
                    {!r.resolved && r.item.stale && (
                      <span className="chip chip-stale" data-testid="stale-chip" title="Its source is failing. Last good data is shown.">
                        stale
                      </span>
                    )}
                  </span>
                </span>
                <span className="item-age">
                  <Age iso={r.since} nowMs={nowMs} />
                </span>
              </button>
            );
          })}
          {rows.length === 0 && (
            <div className="list-empty" data-testid="inbox-empty">
              <strong>{folder === 'resolved' ? 'Nothing resolved in the last 24 h' : 'Nothing needs you'}</strong>
              <div>Last check {ageText(state.generated_at, nowMs)}.</div>
            </div>
          )}
        </div>

        {sel && (
          <article key={sel.item.id} className="mailbox-detail" data-testid="inbox-detail" aria-label="Item detail">
            <button type="button" className="btn back-btn" onClick={() => setDetail(false)}>
              <ArrowLeft size={16} aria-hidden="true" />
              Back
            </button>
            <span className="item-meta detail-meta">
              <span className={`chip chip-${sel.resolved ? 'resolved' : sel.item.kind}`}>
                {sel.resolved ? 'Resolved' : KIND_LABEL[sel.item.kind]}
              </span>
              <span className="mono">{sel.item.repo}</span>
              <span>
                · {sel.resolved ? 'resolved' : 'since'} <Age iso={sel.since} nowMs={nowMs} focusable />
              </span>
              {!sel.resolved && sel.item.stale && <span className="chip chip-stale">stale</span>}
            </span>
            <h2>{sel.item.title}</h2>
            <div className="detail-block">
              <span className="detail-label">Why it matters</span>
              <span>{sel.resolved ? 'The source cleared. No action is needed.' : sel.item.why}</span>
            </div>
            {!sel.resolved && sel.item.owner && <RecommendationBlock item={sel.item.owner} />}
            <div className="detail-block">
              <span className="detail-label">Next step</span>
              <span>{sel.resolved ? 'Nothing.' : sel.item.next}</span>
              <code className="cmd">{sel.item.cmd}</code>
            </div>
            <div className="detail-actions">
              <button type="button" className="btn btn-primary" onClick={() => copySel(sel)}>
                {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                {sel.item.kind === 'waiting' ? 'Copy session name' : 'Copy command'}
              </button>
              {!sel.resolved &&
                (() => {
                  const repo = state.repos.find((r) => samePath(r.path, sel.item.repoPath));
                  const specs = specsFor(repo, sel.item);
                  if (!repo || specs.length === 0) return null;
                  const reason = sel.item.owner ? ownerDisabledReason(repo, sel.item.owner) : undefined;
                  return <ActionButtons repo={repo} specs={specs} act={act} reason={reason} />;
                })()}
            </div>
            <p className="key-hints">
              <kbd>J</kbd> <kbd>K</kbd> move · <kbd>Enter</kbd> open · <kbd>C</kbd> copy
            </p>
          </article>
        )}
      </div>
      <Strips state={state} nowMs={nowMs} />
    </>
  );
}
