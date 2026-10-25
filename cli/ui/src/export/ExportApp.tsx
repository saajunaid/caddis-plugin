import { Home, Menu, Monitor, Moon, OctagonAlert, Sun, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { ExportData } from '../../../src/hub/export/data';
import RoadmapTab from '../repo/RoadmapTab';
import { Logo } from '../shell/Logo';
import { THEME_CHOICES, type ThemeChoice } from '../shell/theme';
import { useTheme } from '../shell/useTheme';
import { bannerText, exportRepo, exportSummary, NEEDS_EMPTY, NOTE_TEXT, routeExport, utcText, type ExportRoute, type ExportSummary } from './summary';

/**
 * The static roadmap page of the Pages export (R60, R63). It shows the Roadmap view in its `site` variant plus a home
 * and a gates page. It makes no request and has no timer: the data is in the page.
 */
const ICON = { dark: Moon, light: Sun, system: Monitor } as const;

function useExportRoute(initial: string | undefined): ExportRoute {
  const [hash, setHash] = useState(() => initial ?? (typeof window === 'undefined' ? '' : window.location.hash));
  useEffect(() => {
    const on = (): void => setHash(window.location.hash);
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return routeExport(hash);
}

function NavLink({ href, active, label, onGo, icon }: { href: string; active: boolean; label: string; onGo: () => void; icon: JSX.Element }): JSX.Element {
  return (
    <li>
      <a className={`nav-link${active ? ' active' : ''}`} href={href} aria-current={active ? 'page' : undefined} onClick={onGo}>
        <span className="nav-link-left">
          {icon}
          <span className="nav-text">{label}</span>
        </span>
      </a>
    </li>
  );
}

function Bar({ done, total, pct }: { done: number; total: number; pct: number }): JSX.Element {
  return (
    <div className="rm-bar-wrap">
      <div className="rm-bar" role="img" aria-label={`${done} of ${total} phases done`}>
        <i style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Kpis({ s }: { s: ExportSummary }): JSX.Element {
  return (
    <section className="kpi-strip" data-testid="ex-kpis" aria-label="Summary">
      <div className="kpi-tile">
        <span className="kpi-label">Needs you</span>
        <span className={`kpi-num${s.needsYou ? ' accent' : ''}`}>{s.needsYou}</span>
      </div>
      <div className="kpi-tile">
        <span className="kpi-label">Phases done</span>
        <span className="kpi-num">
          {s.phasesDone} / {s.phasesTotal}
        </span>
        <Bar done={s.phasesDone} total={s.phasesTotal} pct={s.pct} />
      </div>
      <div className="kpi-tile">
        <span className="kpi-label">Blocked phases</span>
        <span className={`kpi-num${s.blockedPhases ? ' bad' : ''}`}>{s.blockedPhases}</span>
      </div>
    </section>
  );
}

function Needs({ s }: { s: ExportSummary }): JSX.Element {
  return (
    <section className="rm-section" data-testid="ex-needs" aria-label="Needs you">
      <h2 className="flow-h">Needs you</h2>
      {s.needs.length === 0 ? (
        <p className="col-empty">{NEEDS_EMPTY}</p>
      ) : (
        <div className="ex-table-wrap">
          <table className="ex-table">
            <thead>
              <tr>
                <th scope="col">Roadmap</th>
                <th scope="col">Milestone</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {s.needs.map((n, i) => (
                <tr key={i}>
                  <td>
                    <a href={`#/roadmap/${encodeURIComponent(n.roadmap)}`}>{n.roadmap}</a>
                  </td>
                  <td>{n.milestone}</td>
                  <td>{n.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Gates({ s }: { s: ExportSummary }): JSX.Element {
  return (
    <section className="rm-section" data-testid="ex-gates" aria-label="Gates">
      <h1 className="page-title">Gates</h1>
      {s.gates.length === 0 ? (
        <p className="col-empty">No open gate or blocker.</p>
      ) : (
        <ul className="flow-list">
          {s.gates.map((g, i) => (
            <li key={i} className="flow-row">
              <div className="flow-row-head">
                <a href={`#/roadmap/${encodeURIComponent(g.roadmap)}`}>
                  <strong>{g.roadmap}</strong> {g.milestone}
                </a>
                <span className={`chip ${g.type === 'owner-gate' ? 'chip-owner-gate' : 'chip-hub'}`}>{g.type}</span>
              </div>
              <span className="flow-why">{g.reason}</span>
              {g.check && <code className="mono">{g.check}</code>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** `hash` sets the first route: tests and server rendering use it. The browser reads the address. */
export function ExportApp({ data, hash }: { data: ExportData; hash?: string }): JSX.Element {
  const route = useExportRoute(hash);
  const [theme, setTheme] = useTheme();
  const [menu, setMenu] = useState(false);
  const repo = exportRepo(data);
  const s = exportSummary(data);
  const close = (): void => setMenu(false);

  useEffect(() => {
    document.title = route.page === 'roadmap' ? `${route.slug} | roadmap` : route.page === 'gates' ? 'Gates | roadmap' : 'Roadmap';
  }, [route]);

  let body: JSX.Element;
  if (route.page === 'gates') {
    body = <Gates s={s} />;
  } else if (route.page === 'roadmap') {
    body = <RoadmapTab key={route.slug} repo={repo} slug={route.slug} variant="site" />;
  } else {
    body = (
      <>
        <h1 className="page-title">{data.github ?? repo.name}</h1>
        <p className="page-subtitle" data-testid="ex-summary">
          1 repo · {s.roadmaps} {s.roadmaps === 1 ? 'roadmap' : 'roadmaps'} · {s.needsYou} {s.needsYou === 1 ? 'item needs' : 'items that need'} you · generated{' '}
          {utcText(data.generated_at)}
        </p>
        <Kpis s={s} />
        <Needs s={s} />
        <RoadmapTab key="home" repo={repo} slug={null} variant="site" />
      </>
    );
  }

  return (
    <div className="app-shell">
      <header className="mobile-topbar">
        <button type="button" className="menu-btn" aria-label="Open navigation menu" aria-expanded={menu} aria-controls="app-sidebar" onClick={() => setMenu(!menu)}>
          {menu ? <X size={18} /> : <Menu size={18} />}
          <span>Menu</span>
        </button>
        <Logo />
      </header>
      <div className={`drawer-backdrop${menu ? ' open' : ''}`} onClick={close} aria-hidden="true" />
      <aside className={`sidebar${menu ? ' drawer-open' : ''}`} id="app-sidebar">
        <nav className="sidebar-top" aria-label="Main" data-testid="ex-nav">
          <div className="brand-row">
            <Logo />
          </div>
          <ul className="nav-list">
            <NavLink href="#/" active={route.page === 'home'} label="Home" icon={<Home size={18} aria-hidden="true" />} onGo={close} />
            <NavLink href="#/gates" active={route.page === 'gates'} label="Gates" icon={<OctagonAlert size={18} aria-hidden="true" />} onGo={close} />
          </ul>
          <div className="nav-section-label">Roadmaps</div>
          <ul className="nav-list">
            {s.slugs.length === 0 && <li className="nav-empty">No roadmaps</li>}
            {s.slugs.map((slug) => (
              <NavLink
                key={slug}
                href={`#/roadmap/${encodeURIComponent(slug)}`}
                active={route.page === 'roadmap' && route.slug === slug}
                label={slug}
                icon={<span className="repo-dot ok" aria-hidden="true" />}
                onGo={close}
              />
            ))}
          </ul>
        </nav>
        <footer className="sidebar-footer">
          <div className="theme-switch" role="group" aria-label="Theme">
            {THEME_CHOICES.map((c: ThemeChoice) => {
              const Icon = ICON[c];
              return (
                <button key={c} type="button" className={`theme-btn${theme === c ? ' active' : ''}`} aria-pressed={theme === c} title={c} onClick={() => setTheme(c)}>
                  <Icon size={15} aria-hidden="true" />
                  <span>{c}</span>
                </button>
              );
            })}
          </div>
        </footer>
      </aside>
      <main className="main-area" id="main-content">
        <div className="page-wrap">
          <div className="banner warn" data-testid="ex-banner" role="note">
            {bannerText(data)}
          </div>
          {body}
          <p className="page-subtitle ex-note" data-testid="ex-note">
            {NOTE_TEXT}
          </p>
        </div>
      </main>
    </div>
  );
}
