export interface PhaseSection {
  title: string;
  text: string;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function stripPlan(plan: unknown): unknown {
  if (!isRecord(plan) || !isRecord(plan.phases)) return plan;
  const phases: Record<string, { title: string }> = {};
  for (const [k, v] of Object.entries(plan.phases)) {
    const rawTitle = isRecord(v) ? v.title : undefined;
    phases[k] = { title: typeof rawTitle === 'string' ? rawTitle : '' };
  }
  return { ...plan, phases };
}

function stripRepo(repo: unknown): unknown {
  if (!isRecord(repo) || !isRecord(repo.plans) || !Array.isArray(repo.plans.plans)) return repo;
  return {
    ...repo,
    plans: {
      ...repo.plans,
      plans: repo.plans.plans.map(stripPlan),
    },
  };
}

export function stripPhaseText(state: unknown): unknown {
  if (!isRecord(state) || !Array.isArray(state.repos)) return state;
  return {
    ...state,
    repos: state.repos.map(stripRepo),
  };
}

export function findPhaseSection(
  state: unknown,
  repoPath: string,
  planPath: string,
  key: string,
): PhaseSection | null {
  if (!isRecord(state) || !Array.isArray(state.repos)) return null;
  const repo = state.repos.find((r): r is Record<string, unknown> => isRecord(r) && r.path === repoPath);
  if (!repo || !isRecord(repo.plans) || !Array.isArray(repo.plans.plans)) return null;
  const plan = repo.plans.plans.find((p): p is Record<string, unknown> => isRecord(p) && p.path === planPath);
  if (!plan || !isRecord(plan.phases)) return null;
  if (!Object.prototype.hasOwnProperty.call(plan.phases, key)) return null;
  const sec = plan.phases[key];
  if (!isRecord(sec)) return null;
  return {
    title: String(sec.title ?? ''),
    text: String(sec.text ?? ''),
  };
}
