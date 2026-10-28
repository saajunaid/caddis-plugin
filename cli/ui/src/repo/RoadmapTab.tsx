import { Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { clockText } from '../shell/format';
import { repoId as repoIdOf } from '../shell/route';
import type { RepoState } from '../types';
import { isTyping } from './detailParts';
import { ListView, roadmapHref } from './ListView';
import { OtherPlans, Plans } from './PlanList';
import {
  collectorStale,
  deriveRoadmaps,
  filterRoadmap,
  NO_ROADMAP_HINT,
  NO_ROADMAP_TEXT,
  opensDirectly,
  planSourceText,
  type RoadmapView,
} from './roadmap';
import { RoadmapDetail } from './RoadmapDetail';
import { ICON } from './RoadmapTimeline';

export { collectorStale };

/** `hub`: the full view. `site`: the shared copy of the Pages export (R64): no runner, no host, no sessions. */
export type Variant = 'hub' | 'site';

interface Props {
  nowMs?: number;
  repo: RepoState;
  /** The roadmap the route names, or null. */
  slug: string | null;
  /** True when the collector data is old (the hub passes `collectorStale(state)`). */
  stale?: boolean;
  /** When the collector last read well. */
  lastOkAt?: string | null;
  variant?: Variant;
  initialView?: RoadmapView;
  initialOpenAll?: boolean;
}

export default function RoadmapTab({ repo, slug, stale = false, lastOkAt = null, variant = 'hub', initialView, initialOpenAll = false, nowMs }: Props): JSX.Element {
  const m = deriveRoadmaps(repo);
  const [text, setText] = useState('');
  const search = useRef<HTMLInputElement>(null);

  // `/` focuses the search box, Escape clears it (parity P16).
  useEffect(() => {
    const on = (e: KeyboardEvent): void => {
      if (e.key === '/' && !isTyping(e.target) && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault();
        search.current?.focus();
      }
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, []);

  const id = repoIdOf(repo);
  const staleNote = stale && (
    <p className="lane-note" data-testid="rm-stale">
      Roadmap data is old. Last good read {clockText(lastOkAt)}. The numbers below are greyed.
    </p>
  );

  const src = variant === 'hub' ? planSourceText(repo.plans, nowMs ?? Date.now()) : null;
  const sourceNote = src && <p className={`page-subtitle rm-source${src.old ? ' tone-warn' : ''}`} data-testid="rm-source">{src.text}</p>;

  let body: JSX.Element;
  if (m.mode === 'none') {
    body = (
      <div className="notice" data-testid="rm-none">
        <h2 className="rm-title">{NO_ROADMAP_TEXT}</h2>
        <p>
          Create one with <code className="cmd">{NO_ROADMAP_HINT}</code>.
        </p>
      </div>
    );
  } else if (m.mode === 'error') {
    body = (
      <div className="lane-note" data-testid="rm-errors">
        Could not read this repo: {m.repoError}
      </div>
    );
  } else if (m.mode === 'plans') {
    body = <Plans plans={m.plans} repo={repo} variant={variant} initialView={initialView} initialOpenAll={initialOpenAll} />;
  } else {
    // The site home always lists: its KPIs and gates sit above the list.
    const picked = slug ? m.roadmaps.find((r) => r.slug === slug) : variant === 'hub' && opensDirectly(m) ? m.roadmaps[0] : undefined;
    if (picked) {
      const canList = m.roadmaps.length + m.errors.length > 1;
      const match = filterRoadmap(picked, text);
      body = (
        <>
          <div className="rm-searchbar">
            <label className="rm-search">
              <Search {...ICON} />
              <span className="sr-only">Search this roadmap</span>
              <input
                ref={search}
                type="search"
                data-testid="rm-search"
                placeholder="Search phases, PRs, milestones (press /)"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setText('');
                }}
              />
            </label>
            <span className="rm-match" data-testid="rm-match-count" aria-live="polite">
              {match ? `${match.count} ${match.count === 1 ? 'match' : 'matches'}` : ''}
            </span>
          </div>
          <RoadmapDetail m={picked} plans={m.plans} repo={repo} crumbHref={canList ? roadmapHref(variant, id) : null} match={match} variant={variant} initialView={initialView} />
        </>
      );
    } else {
      body = (
        <>
          {slug && (
            <p className="lane-note" data-testid="rm-missing">
              No roadmap named {slug} in this repo.
            </p>
          )}
          <ListView repo={repo} m={m} variant={variant} />
        </>
      );
    }
  }

  return (
    <div className={`rm${stale ? ' stale' : ''}`} data-testid="roadmap-tab">
      {staleNote}
      {sourceNote}
      {body}
      {m.mode === 'roadmaps' ? <OtherPlans plans={m.otherPlans} repo={repo} variant={variant} initialView={initialView} initialOpenAll={initialOpenAll} /> : null}
    </div>
  );
}
