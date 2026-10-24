import { Activity, BookOpen, Inbox as InboxIcon, LayoutDashboard, Menu, X } from 'lucide-react';
import type { ReactNode } from 'react';
import type { HubState, RepoState } from '../types';
import { Logo } from './Logo';
import { repoHref, type Route } from './route';

export type RepoTone = 'ok' | 'attention' | 'blocked' | 'idle';

/** The status dot of a repo: red on an error, yellow on a stale coordinator or a waiting session. */
export function repoTone(repo: RepoState, state: HubState): RepoTone {
  if (repo.error || repo.github?.error) return 'blocked';
  const waiting = state.sessions.some((s) => s.repo_path === repo.path && s.waiting_class === 'owner');
  if (waiting) return 'attention';
  if (repo.coordinator && state.sources.coordinator.stale) return 'attention';
  const quiet = !repo.coordinator && !state.sessions.some((s) => s.repo_path === repo.path);
  return quiet ? 'idle' : 'ok';
}

export const repoId = (r: RepoState): string => r.repo_id ?? r.path;

interface Props {
  route: Route;
  state: HubState | null;
  inbox: number;
  open: boolean;
  onToggle: (open: boolean) => void;
  /** The footer, shown at the bottom of the sidebar. */
  children?: ReactNode;
}

function Link({ href, active, icon, label, badge, onGo }: {
  href: string;
  active: boolean;
  icon: JSX.Element;
  label: string;
  badge?: JSX.Element | undefined;
  onGo: () => void;
}): JSX.Element {
  return (
    <li>
      <a className={`nav-link${active ? ' active' : ''}`} href={href} aria-current={active ? 'page' : undefined} onClick={onGo}>
        <span className="nav-link-left">
          {icon}
          <span className="nav-text">{label}</span>
        </span>
        {badge}
      </a>
    </li>
  );
}

export function Nav({ route, state, inbox, open, onToggle, children }: Props): JSX.Element {
  const close = (): void => onToggle(false);
  return (
    <>
      <header className="mobile-topbar">
        <button
          type="button"
          className="menu-btn"
          aria-label="Open navigation menu"
          aria-expanded={open}
          aria-controls="app-sidebar"
          onClick={() => onToggle(!open)}
        >
          {open ? <X size={18} /> : <Menu size={18} />}
          <span>Menu</span>
        </button>
        <Logo />
      </header>
      <div className={`drawer-backdrop${open ? ' open' : ''}`} onClick={close} aria-hidden="true" />
      <aside className={`sidebar${open ? ' drawer-open' : ''}`} id="app-sidebar">
        <nav className="sidebar-top" aria-label="Main">
          <div className="brand-row">
            <Logo />
          </div>
          <ul className="nav-list">
            <Link
              href="#/inbox"
              active={route.page === 'inbox'}
              icon={<InboxIcon size={18} />}
              label="Inbox"
              badge={inbox > 0 ? <span className="inbox-badge">{inbox}</span> : undefined}
              onGo={close}
            />
            <Link href="#/overview" active={route.page === 'overview'} icon={<LayoutDashboard size={18} />} label="Overview" onGo={close} />
          </ul>
          <div className="nav-section-label">Repos</div>
          <ul className="nav-list">
            {state?.repos.length === 0 && <li className="nav-empty">No repos yet</li>}
            {state?.repos.map((r) => {
              const id = repoId(r);
              const active = route.page === 'repo' && route.id === id;
              return (
                <Link
                  key={r.path}
                  href={repoHref(id)}
                  active={active}
                  icon={<span className={`repo-dot ${repoTone(r, state)}`} aria-hidden="true" />}
                  label={r.name}
                  onGo={close}
                />
              );
            })}
          </ul>
          <div className="nav-section-label">More</div>
          <ul className="nav-list">
            <Link href="#/activity" active={route.page === 'activity'} icon={<Activity size={18} />} label="Activity" badge={<span className="soon">soon</span>} onGo={close} />
            <Link href="#/guide" active={route.page === 'guide'} icon={<BookOpen size={18} />} label="caddis guide" badge={<span className="soon">soon</span>} onGo={close} />
          </ul>
        </nav>
        {children}
      </aside>
    </>
  );
}
