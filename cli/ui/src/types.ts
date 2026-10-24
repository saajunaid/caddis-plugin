// Types only: Vite strips this import, so no server code reaches the bundle.
export type { HubState, RepoState, SourceName, SourceStatus } from '../../src/hub/state.js';
export type { SessionEntry } from '../../src/hub/sources/agents.js';

/** The state schema this UI understands. A higher value means the hub is older than its data. */
export const SUPPORTED_SCHEMA = 1;
