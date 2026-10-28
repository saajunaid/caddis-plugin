import { useContext, useEffect, useRef, useState } from 'react';
import type { RepoState } from '../types';
import { PhaseLoaderContext } from './phaseLoader';
import { PhasePanel } from './PhasePanel';
import {
  phaseDetail,
  readView,
  writeView,
  type PlanView,
  type RoadmapModel,
  type RoadmapView,
} from './roadmap';
import type { Variant } from './RoadmapTab';

export function getStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function useRoadmapView(initialView?: RoadmapView): [RoadmapView, (v: RoadmapView) => () => void] {
  const [view, setView] = useState<RoadmapView>(() => initialView ?? readView(getStorage()));
  const chooseView = (v: RoadmapView) => () => {
    setView(v);
    writeView(getStorage(), v);
  };
  return [view, chooseView];
}

export function ViewSwitch({ view, choose }: { view: RoadmapView; choose: (v: RoadmapView) => () => void }): JSX.Element {
  return (
    <div className="rm-view" role="group" aria-label="View" data-testid="rm-view">
      <button type="button" data-testid="rm-view-timeline" aria-pressed={view === 'timeline'} onClick={choose('timeline')}>
        Timeline
      </button>
      <button type="button" data-testid="rm-view-board" aria-pressed={view === 'board'} onClick={choose('board')}>
        Board
      </button>
    </div>
  );
}

export const isTyping = (t: EventTarget | null): boolean => t instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);

export function usePhasePanel({
  m,
  pool,
  repo,
  variant,
}: {
  m: RoadmapModel;
  pool: PlanView[];
  repo: RepoState;
  variant: Variant;
}): { open: (ref: string, el: HTMLElement) => void; panel: JSX.Element } {
  const [selected, setSelected] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<{ ref: string; text: string | null; error: boolean } | null>(null);
  const [retry, setRetry] = useState(0);
  const opener = useRef<HTMLElement | null>(null);
  const detail = selected ? phaseDetail(m, pool, selected) : null;
  const loadPhase = useContext(PhaseLoaderContext);
  const planPath = detail?.planPath;
  const key = detail?.key;
  const needsFetch = detail !== null && variant !== 'site' && detail.hasSection && detail.text === null && detail.planPath !== null && loadPhase !== null;
  useEffect(() => {
    if (!needsFetch || !selected || !detail || !detail.planPath || !loadPhase) return;
    let live = true;
    loadPhase(repo.path, detail.planPath, detail.key).then(
      (s) => {
        if (live) setLoaded({ ref: selected, text: s.text || null, error: false });
      },
      () => {
        if (live) setLoaded({ ref: selected, text: null, error: true });
      },
    );
    return () => {
      live = false;
    };
  }, [selected, needsFetch, loadPhase, repo.path, planPath, key, retry]);
  const got = loaded && loaded.ref === selected ? loaded : null;
  const open = (ref: string, el: HTMLElement) => {
    opener.current = el;
    if (ref === selected) {
      // The open tile stays clickable (the panel is non-modal): keep the panel, but retry after an error.
      if (got?.error) {
        setLoaded(null);
        setRetry((n) => n + 1);
      }
      return;
    }
    setLoaded(null);
    setSelected(ref);
  };
  const close = () => {
    setLoaded(null);
    setSelected(null);
    opener.current?.focus();
  };
  useEffect(() => {
    if (selected === null) return;
    const on = (e: KeyboardEvent): void => {
      if (isTyping(e.target)) return;
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, [selected]);
  const panel = (
    <PhasePanel detail={detail ? { title: detail.title, text: detail.text ?? got?.text ?? null, phase: detail.phase } : null} note={needsFetch && !got ? 'loading' : got?.error ? 'error' : null} variant={variant} onClose={close} />
  );
  return { open, panel };
}
