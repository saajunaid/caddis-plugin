import { lazy, Suspense, useEffect, useState } from 'react';
import { useActions } from './actions/useActions';
import { Inbox } from './inbox/Inbox';
import { useInbox } from './inbox/useInbox';
import { Overview } from './overview/Overview';
import { RepoPage } from './repo/RepoPage';
import { Banners } from './shell/Banners';
import { Footer } from './shell/Footer';
import { Nav, repoId } from './shell/Nav';
import { setFavicon } from './shell/favicon';
import { titleFor } from './shell/format';
import { parseRoute } from './shell/route';
import { useTheme } from './shell/useTheme';
import { useMotion } from './shell/useMotion';
import { useHubState } from './useHubState';

// The guide page loads on demand, so its code and CSS stay out of the first bundle (G6).
const Guide = lazy(() => import('./guide/Guide').then((m) => ({ default: m.Guide })));
// The Activity page is its own chunk (R54).
const Activity = lazy(() => import('./activity/Activity'));

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

export function App(): JSX.Element {
  const { state, error, loading, refresh } = useHubState();
  const act = useActions(refresh);
  const nowMs = useNow(5_000);
  const route = useRoute();
  const [theme, setTheme] = useTheme();
  const [motion, setMotion] = useMotion();
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
    body = <Inbox state={state} nowMs={nowMs} api={api} act={act} />;
  } else if (route.page === 'overview') {
    body = <Overview state={state} nowMs={nowMs} api={api} act={act} />;
  } else if (route.page === 'repo') {
    const repo = state.repos.find((r) => repoId(r) === route.id);
    body = repo ? (
      <RepoPage key={route.id} state={state} repo={repo} nowMs={nowMs} act={act} tab={route.tab} roadmap={route.roadmap} />
    ) : (
      <div className="notice">
        <h1 className="page-title">{route.id}</h1>
        <p>This repo is not in the hub registry.</p>
      </div>
    );
  } else if (route.page === 'guide') {
    body = (
      <Suspense fallback={<p className="page-subtitle">Loading...</p>}>
        <Guide guide={state.guide} versions={state.versions} tab={route.tab} item={route.item} />
      </Suspense>
    );
  } else {
    // The last page of `parseRoute` is Activity.
    body = (
      <Suspense fallback={<p className="page-subtitle">Loading...</p>}>
        <Activity state={state} />
      </Suspense>
    );
  }

  return (
    <div className="app-shell">
      <Nav route={route} state={state} inbox={count} open={menu} onToggle={setMenu}>
        <Footer state={state} nowMs={nowMs} theme={theme} onTheme={setTheme} motion={motion} onMotion={setMotion} />
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
