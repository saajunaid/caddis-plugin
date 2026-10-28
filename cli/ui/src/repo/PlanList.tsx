import { useState } from 'react';
import type { RepoState } from '../types';
import { PlanKpiLine } from './PlanBoard';
import { PlanDetail } from './PlanDetail';
import { initiallyOpenPlan, planRoadmapModel, type PlanView, type RoadmapView } from './roadmap';
import type { Variant } from './RoadmapTab';

/** The board that starts open is picked once, so a data refresh never opens or closes a board under the reader. */
function usePlanToOpen(plans: PlanView[]): string | null {
  const [path] = useState(() => initiallyOpenPlan(plans));
  return path;
}

function PlanItem({
  plan,
  repo,
  variant,
  initialView,
  defaultOpen,
}: {
  plan: PlanView;
  repo: RepoState;
  variant: Variant;
  initialView?: RoadmapView;
  defaultOpen: boolean;
}): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details className="rm-plan" aria-label={plan.title} open={open || undefined} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="rm-plan-sum">
        <span className="rm-plan-title">{plan.title}</span>
        <span className="rm-sub">{plan.open} open</span>
        <PlanKpiLine plan={plan} />
        <span className="rm-plan-only">plan only, no runner</span>
      </summary>
      {open && <PlanDetail m={planRoadmapModel(repo, plan)} plan={plan} repo={repo} variant={variant} initialView={initialView} />}
    </details>
  );
}

function PlanList({
  plans,
  repo,
  variant,
  initialView,
  initialOpenAll,
}: {
  plans: PlanView[];
  repo: RepoState;
  variant: Variant;
  initialView?: RoadmapView;
  initialOpenAll: boolean;
}): JSX.Element {
  const openPath = usePlanToOpen(plans);
  return (
    <>
      {plans.map((plan) => (
        <PlanItem key={plan.path} plan={plan} repo={repo} variant={variant} initialView={initialView} defaultOpen={initialOpenAll || plan.path === openPath} />
      ))}
    </>
  );
}

export function Plans({
  plans,
  repo,
  variant,
  initialView,
  initialOpenAll = false,
}: {
  plans: PlanView[];
  repo: RepoState;
  variant: Variant;
  initialView?: RoadmapView;
  initialOpenAll?: boolean;
}): JSX.Element {
  return (
    <div className="flow" data-testid="rm-plans">
      <p className="page-subtitle">No roadmap here. These plans are active. Click a plan to open or close it.</p>
      <PlanList plans={plans} repo={repo} variant={variant} initialView={initialView} initialOpenAll={initialOpenAll} />
    </div>
  );
}

/** Open plans that no roadmap names, under the roadmap view. */
export function OtherPlans({
  plans,
  repo,
  variant,
  initialView,
  initialOpenAll = false,
}: {
  plans: PlanView[];
  repo: RepoState;
  variant: Variant;
  initialView?: RoadmapView;
  initialOpenAll?: boolean;
}): JSX.Element | null {
  if (plans.length === 0) return null;
  return (
    <div className="flow" data-testid="rm-other-plans">
      <h2 className="rm-title">Plans with no roadmap</h2>
      <PlanList plans={plans} repo={repo} variant={variant} initialView={initialView} initialOpenAll={initialOpenAll} />
    </div>
  );
}
