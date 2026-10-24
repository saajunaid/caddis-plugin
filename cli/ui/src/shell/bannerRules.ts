import { SUPPORTED_SCHEMA, type HubState, type SourceName } from '../types';
import { clockText } from './format';

export interface BannerItem {
  id: string;
  tone: 'warn' | 'bad';
  text: string;
  /** A shell command shown in a code box. */
  command?: string;
}

const LABEL: Record<SourceName, string> = {
  collector: 'Plans and roadmaps',
  agents: 'Claude sessions',
  github: 'GitHub',
  coordinator: 'Coordinator',
};

/** The banners for a state. Pure, so tests can check each rule. */
export function bannersFor(state: HubState): BannerItem[] {
  const out: BannerItem[] = [];
  if (state.schema > SUPPORTED_SCHEMA || state.update_needed) {
    out.push({
      id: 'schema',
      tone: 'bad',
      text: 'This hub is older than its data. Update the hub:',
      command: 'npm i -g @caddis/cli@latest',
    });
  }
  const agents = state.sources?.agents;
  if (agents && !agents.ok) {
    out.push({
      id: 'agents-failed',
      tone: 'bad',
      text: `Session list unavailable: "claude agents" failed${agents.last_error ? ` (${agents.last_error})` : ''}.`,
    });
  }
  for (const name of Object.keys(LABEL) as SourceName[]) {
    const s = state.sources?.[name];
    if (!s?.stale) continue;
    if (name === 'agents' && !s.ok) continue;
    out.push({
      id: `stale-${name}`,
      tone: 'warn',
      text: `${LABEL[name]} data is stale. Last good read: ${s.last_ok_at ? clockText(s.last_ok_at) : 'never'}.`,
    });
  }
  return out;
}
