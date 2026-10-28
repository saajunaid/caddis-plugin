import type { RepoState } from '../types';
import { usePhasePanel, useRoadmapView, ViewSwitch } from './detailParts';
import { PlanColumns } from './PlanBoard';
import type { PlanView, RoadmapModel, RoadmapView } from './roadmap';
import type { Variant } from './RoadmapTab';
import { Milestones, Timeline } from './RoadmapTimeline';

export function PlanDetail({
  m,
  plan,
  repo,
  variant,
  initialView,
}: {
  m: RoadmapModel;
  plan: PlanView;
  repo: RepoState;
  variant: Variant;
  initialView?: RoadmapView;
}): JSX.Element {
  const [view, chooseView] = useRoadmapView(initialView);
  const { open, panel } = usePhasePanel({ m, pool: [plan], repo, variant });
  const k = m.kpis;
  return (
    <div className="rm-detail" data-testid="rm-detail">
      {m.detailError && (
        <div className="lane-note" data-testid="rm-errors">
          Roadmap detail is unavailable: {m.detailError}. Phase names, Tracker cells and PR links are missing.
        </div>
      )}
      <header data-testid="rm-header">
        <p className="page-subtitle">
          {k.phasesDone} of {k.phasesTotal} phases done
        </p>
      </header>

      <ViewSwitch view={view} choose={chooseView} />

      <section className="rm-kpis kpi-strip" data-testid="rm-kpis" aria-label="Summary">
        <div className="kpi-tile">
          <span className="kpi-label">Phases done</span>
          <span className="kpi-num">{k.phasesDone} / {k.phasesTotal}</span>
        </div>
        <div className="kpi-tile">
          <span className="kpi-label">In progress</span>
          <span className="kpi-num">{k.inProgress.length}</span>
          <span className="kpi-sub tone-muted">{k.inProgress.join(', ') || 'none'}</span>
        </div>
      </section>

      {view === 'timeline' ? <Timeline m={m} match={null} onOpen={open} /> : <PlanColumns plan={plan} />}

      <Milestones m={m} match={null} onOpen={open} />

      {panel}
    </div>
  );
}
