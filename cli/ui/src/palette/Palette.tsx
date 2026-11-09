import { Archive, Copy, ExternalLink, GitMerge, Inbox as InboxIcon, LayoutDashboard, Rocket, Search, Terminal } from 'lucide-react';
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import type { InboxItem } from '../inbox/derive';
import { tryCopy } from '../shell/clipboard';
import type { HubState } from '../types';
import { buildPaletteItems, type PaletteGroup, type PaletteItem } from './items';
import { groupResults, rankItems } from './match';
import './palette.css';

const GROUP_ICON: Record<PaletteGroup, JSX.Element> = {
  Pages: <LayoutDashboard size={16} />,
  Repos: <Archive size={16} />,
  Roadmaps: <Rocket size={16} />,
  'Pull requests': <GitMerge size={16} />,
  Sessions: <Terminal size={16} />,
  Inbox: <InboxIcon size={16} />,
};

const COPY_CLOSE_MS = 700;
const LIST_ID = 'pal-list';
const optId = (n: number): string => `pal-opt-${n}`;
const resultText = (n: number): string => (n === 1 ? '1 result' : `${n} results`);

interface Props {
  state: HubState;
  inbox: InboxItem[];
  nowMs: number;
  onClose: () => void;
}

/** "Jump to anything" (Ctrl K): a modal search over pages, repos, roadmaps, PRs, sessions and Inbox items. */
export default function Palette({ state, inbox, nowMs, onClose }: Props): JSX.Element {
  // The list is built once per open: a poll while the palette is open does not move the rows under the cursor.
  const [items] = useState(() => buildPaletteItems(state, inbox, nowMs));
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const timer = useRef<number | null>(null);
  const alive = useRef(true);

  const groups = useMemo(() => groupResults(rankItems(items, query)), [items, query]);
  const flat = useMemo(() => groups.flatMap(([, list]) => list), [groups]);
  const at = flat.length ? Math.min(active, flat.length - 1) : -1;

  // Focus moves in before the first paint, so a key pressed as soon as the dialog shows goes to the field.
  useLayoutEffect(() => {
    alive.current = true;
    input.current?.focus();
    return () => {
      alive.current = false;
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  useEffect(() => {
    if (at >= 0) document.getElementById(optId(at))?.scrollIntoView?.({ block: 'nearest' });
  }, [at]);

  const run = (item: PaletteItem | undefined): void => {
    if (!item) return;
    const a = item.action;
    if (a.kind === 'route') {
      onClose();
      window.location.hash = a.href;
    } else if (a.kind === 'url') {
      window.open(a.url, '_blank', 'noopener,noreferrer');
      onClose();
    } else {
      void tryCopy(a.text).then((ok) => {
        if (!alive.current) return;
        setMsg(ok ? 'Copied' : 'Copy failed');
        if (ok) timer.current = window.setTimeout(onClose, COPY_CLOSE_MS);
      });
    }
  };

  const onDialogKey = (e: ReactKeyboardEvent<HTMLDivElement>): void => {
    // Keys in the palette never reach the page's own shortcuts (Inbox J/K, `/`, the drawer).
    e.stopPropagation();
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'Tab') {
      // Focus stays in the dialog: the input and the close button.
      e.preventDefault();
      (document.activeElement === input.current ? closeBtn.current : input.current)?.focus();
    }
  };

  const onInputKey = (e: ReactKeyboardEvent<HTMLInputElement>): void => {
    const n = flat.length;
    let to: number | null = null;
    if (e.key === 'ArrowDown') to = n ? (at + 1) % n : null;
    else if (e.key === 'ArrowUp') to = n ? (at - 1 + n) % n : null;
    else if (e.key === 'Home') to = n ? 0 : null;
    else if (e.key === 'End') to = n ? n - 1 : null;
    else if (e.key === 'Enter') {
      e.preventDefault();
      run(flat[at]);
      return;
    } else return;
    e.preventDefault();
    if (to !== null) setActive(to);
  };

  let n = -1;
  return (
    <div className="pal-root">
      <div className="pal-backdrop" data-testid="palette-backdrop" aria-hidden="true" onClick={onClose} />
      <div className="pal-panel" role="dialog" aria-modal="true" aria-label="Jump to anything" onKeyDown={onDialogKey}>
        <div className="pal-head">
          <Search size={17} className="pal-search" aria-hidden="true" />
          <input
            ref={input}
            className="pal-input"
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-controls={LIST_ID}
            aria-autocomplete="list"
            aria-activedescendant={at >= 0 ? optId(at) : undefined}
            aria-label="Jump to anything"
            placeholder="Jump to a page, repo, PR or session"
            autoComplete="off"
            spellCheck={false}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
              setMsg(null);
            }}
            onKeyDown={onInputKey}
          />
          <button ref={closeBtn} type="button" className="pal-esc" aria-label="Close" onClick={onClose}>
            Esc
          </button>
        </div>
        <div className="pal-body">
          <div className="pal-list" role="listbox" id={LIST_ID} aria-label="Results">
            {groups.map(([group, list]) => (
              <div key={group} role="group" aria-labelledby={`pal-g-${group.replace(/\s+/g, '-')}`}>
                <div className="pal-group-label" role="presentation" id={`pal-g-${group.replace(/\s+/g, '-')}`}>
                  {group}
                </div>
                {list.map((item) => {
                  n += 1;
                  const index = n;
                  const sel = index === at;
                  return (
                    <div
                      key={item.id}
                      id={optId(index)}
                      role="option"
                      aria-selected={sel}
                      className={`pal-opt${sel ? ' sel' : ''}`}
                      data-testid="palette-option"
                      onMouseMove={() => {
                        if (!sel) setActive(index);
                      }}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => run(item)}
                    >
                      <span className="pal-ico" aria-hidden="true">
                        {GROUP_ICON[item.group]}
                      </span>
                      <span className="pal-label">{item.label}</span>
                      {item.hint && <span className="pal-hint">{item.hint}</span>}
                      {item.action.kind === 'url' && (
                        <>
                          <ExternalLink size={14} className="pal-act" aria-hidden="true" />
                          <span className="sr-only">, opens in a new tab</span>
                        </>
                      )}
                      {item.action.kind === 'copy' && (
                        <>
                          <Copy size={14} className="pal-act" aria-hidden="true" />
                          <span className="sr-only">, copies the name</span>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
          {flat.length === 0 && <div className="pal-empty">No match</div>}
        </div>
        <div className="pal-foot">
          <span className="pal-keys" aria-hidden="true">
            <kbd>↑</kbd>
            <kbd>↓</kbd> move · <kbd>Enter</kbd> open · <kbd>Esc</kbd> close
          </span>
          <span className={`pal-status${msg === 'Copy failed' ? ' bad' : ''}`} role="status" aria-live="polite" data-testid="palette-status">
            {msg ?? resultText(flat.length)}
          </span>
        </div>
      </div>
    </div>
  );
}
