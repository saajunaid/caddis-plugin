import { useEffect, useState } from 'react';
import { Inbox } from './inbox/Inbox';
import { useInbox } from './inbox/useInbox';
import { Overview } from './overview/Overview';
import { Banners } from './shell/Banners';
import { Footer } from './shell/Footer';
import { Nav, repoId } from './shell/Nav';
import { setFavicon } from './shell/favicon';
import { titleFor } from './shell/format';
import { parseRoute } from './shell/route';
import { loadTheme, resolveTheme, saveTheme, type ThemeChoice } from './shell/theme';
import { useHubState } from './useHubState';

const systemDark = (): boolean => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true;

function useNow(everyMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), everyMs);
    return () => window.clearInterval(id);
  }, [everyMs]);
  return now;
}

function useRoute() {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const on = (): void => setHash(window.location.hash);
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return parseRoute(hash);
}

function useTheme(): [ThemeChoice, (t: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() => loadTheme());
  useEffect(() => {
    const apply = (): void => {
      document.documentElement.dataset.theme = resolveTheme(choice, systemDark());
    };
    apply();
    if (choice !== 'system' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [choice]);
  return [
    choice,
    (t) => {
      saveTheme(t);
      setChoice(t);
    },
  ];
}

export function App(): JSX.Element {
  const { state, error, loading } = useHubState();
  const nowMs = useNow(5_000);
  const route = useRoute();
  const [theme, setTheme] = useTheme();
  const [menu, setMenu] = useState(false);
  const api = useInbox(state, nowMs);
  const count = api.model.items.length;

  useEffect(() => {
    document.title = titleFor(count);
    setFavicon(count > 0);
  }, [count]);

  let body: JSX.Element;
  if (error === 'unauthorized') {
    body = (
      <div className="notice" data-testid="signin">
        <h1 className="page-title">Signed out</h1>
        <p>
          Run <code className="cmd">caddis hub open</code> to sign in.
        </p>
      </div>
    );
  } else if (!state) {
    body = <p className="page-subtitle">{loading ? 'Loading...' : 'The hub did not answer. Retrying.'}</p>;
  } else if (route.page === 'inbox') {
    body = <Inbox state={state} nowMs={nowMs} api={api} />;
  } else if (route.page === 'overview') {
    body = <Overview state={state} nowMs={nowMs} api={api} />;
  } else if (route.page === 'repo') {
    const repo = state.repos.find((r) => repoId(r) === route.id);
    body = (
      <div className="notice">
        <h1 className="page-title">{repo?.name ?? route.id}</h1>
        <p>Repo page arrives in H4.</p>
      </div>
    );
  } else {
    body = (
      <div className="notice">
        <h1 className="page-title">{route.page === 'activity' ? 'Activity' : 'caddis guide'}</h1>
        <p>Coming soon.</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Nav route={route} state={state} inbox={count} open={menu} onToggle={setMenu}>
        <Footer state={state} nowMs={nowMs} theme={theme} onTheme={setTheme} />
      </Nav>
      <main className="main-area" id="main-content">
        <div className="page-wrap">
          {state && <Banners state={state} />}
          {error === 'network' && state && <div className="banner warn" role="status">The hub did not answer. Showing the last data.</div>}
          {body}
        </div>
      </main>
    </div>
  );
}
