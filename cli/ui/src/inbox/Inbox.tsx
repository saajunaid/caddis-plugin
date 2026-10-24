import { Archive, ArrowLeft, Bell, Check, Copy, ShieldCheck, ShieldOff } from 'lucide-react';
import { useState } from 'react';
import { ageText, anySourceDown } from '../shell/format';
import type { HubState } from '../types';
import { KIND_LABEL, type Folder, type InboxItem } from './derive';
import { FirstRun } from '../shell/FirstRun';
import { Tiles } from './Tiles';
import type { InboxApi } from './useInbox';

const FOLDERS: { id: Folder; label: string; Icon: typeof Bell }[] = [
  { id: 'needs', label: 'Needs you', Icon: Bell },
  { id: 'approvals', label: 'Approvals', Icon: ShieldCheck },
  { id: 'blocked', label: 'Blocked', Icon: ShieldOff },
  { id: 'resolved', label: 'Resolved, 24 h', Icon: Archive },
];

const shortAge = (iso: string | null, now: number): string => (iso ? ageText(iso, now).replace(/ ago$/, '') : 'unknown');

interface Row {
  item: InboxItem;
  resolved: boolean;
  /** ISO time shown as "since". */
  since: string | null;
}

function copy(text: string): void {
  try {
    void navigator.clipboard?.writeText(text);
  } catch {
    /* clipboard can be blocked */
  }
}

export function Inbox({ state, nowMs, api }: { state: HubState; nowMs: number; api: InboxApi }): JSX.Element {
  const [folder, setFolder] = useState<Folder>('needs');
  const [selId, setSelId] = useState<string | null>(null);
  const [detail, setDetail] = useState(false);
  const [copied, setCopied] = useState(false);
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
  };
  const pickItem = (r: Row): void => {
    setSelId(r.item.id);
    setDetail(true);
    if (!r.resolved) api.markRead(r.item.id);
  };

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">Inbox</h1>
        <span className="page-subtitle">
          {state.repos.length} repos · {state.sessions.length} sessions
        </span>
      </div>
      {state.repos.length === 0 && <FirstRun />}
      <Tiles tiles={model.tiles} stale={anySourceDown(state)} />
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
        <div className="mailbox-folders" role="tablist" aria-label="Folders">
          {FOLDERS.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={folder === id}
              className={`folder-btn${folder === id ? ' sel' : ''}`}
              onClick={() => pickFolder(id)}
              data-testid={`folder-${id}`}
            >
              <Icon size={16} aria-hidden="true" />
              <span>{label}</span>
              <strong>{counts[id]}</strong>
            </button>
          ))}
        </div>

        <div className="mailbox-list" data-testid="inbox-list">
          {rows.map((r) => {
            const unread = !r.resolved && !read.has(r.item.id);
            return (
              <button
                key={r.item.id}
                type="button"
                className={`item-btn${sel?.item.id === r.item.id ? ' sel' : ''}`}
                onClick={() => pickItem(r)}
                data-testid="inbox-item"
              >
                <span className={`unread-dot${unread ? ' on' : ''}`} role="img" aria-label={unread ? 'Unread' : 'Read'} />
                <span className="item-main">
                  <span className="item-meta">
                    <span className={`chip chip-${r.resolved ? 'resolved' : r.item.kind}`}>
                      {r.resolved ? 'Resolved' : KIND_LABEL[r.item.kind]}
                    </span>
                    <span className="mono">{r.item.repo}</span>
                    <span>· {shortAge(r.since, nowMs)}</span>
                    {!r.resolved && r.item.stale && (
                      <span className="chip chip-stale" data-testid="stale-chip" title="Its source is failing. Last good data is shown.">
                        stale
                      </span>
                    )}
                  </span>
                  <span className="item-title">{r.item.title}</span>
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
          <article className="mailbox-detail" data-testid="inbox-detail" aria-label="Item detail">
            <button type="button" className="btn back-btn" onClick={() => setDetail(false)}>
              <ArrowLeft size={16} aria-hidden="true" />
              Back
            </button>
            <span className="item-meta">
              <span className={`chip chip-${sel.resolved ? 'resolved' : sel.item.kind}`}>
                {sel.resolved ? 'Resolved' : KIND_LABEL[sel.item.kind]}
              </span>
              <span className="mono">{sel.item.repo}</span>
              <span>
                · {sel.resolved ? 'resolved' : 'since'} {shortAge(sel.since, nowMs)}
              </span>
              {!sel.resolved && sel.item.stale && <span className="chip chip-stale">stale</span>}
            </span>
            <h2>{sel.item.title}</h2>
            <div className="detail-block">
              <span className="detail-label">Why it matters</span>
              <span>{sel.resolved ? 'The source cleared. No action is needed.' : sel.item.why}</span>
            </div>
            <div className="detail-block">
              <span className="detail-label">Next step</span>
              <span>{sel.resolved ? 'Nothing.' : sel.item.next}</span>
              <code className="cmd">{sel.item.cmd}</code>
            </div>
            <div className="detail-actions">
              <button
                type="button"
                className="btn"
                onClick={() => {
                  copy(sel.item.cmd);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}
                {sel.item.kind === 'waiting' ? 'Copy session name' : 'Copy command'}
              </button>
              {!sel.resolved && sel.item.action && (
                <button type="button" className="btn" disabled title="Actions arrive in H3">
                  {sel.item.action} (H3)
                </button>
              )}
            </div>
          </article>
        )}
      </div>
    </>
  );
}
