import { FolderPlus, Terminal } from 'lucide-react';

export const ACTIONS_LATER = 'Actions arrive in H3';

/** The first-run page: no repo is known yet. Adding a folder needs an action route, so it waits for H3 (R28). */
export function FirstRun(): JSX.Element {
  return (
    <section className="first-run" data-testid="first-run" aria-label="Get started">
      <h2>No repos yet</h2>
      <p>
        <Terminal size={16} aria-hidden="true" /> Start a Claude Code session in a repo. The hub finds it by itself.
      </p>
      <p>Or add a folder. The hub checks that it is a git repo.</p>
      <button type="button" className="btn" disabled title={ACTIONS_LATER} data-testid="add-folder">
        <FolderPlus size={16} aria-hidden="true" />
        Add a folder
      </button>
      <span className="first-run-reason"> {ACTIONS_LATER}</span>
    </section>
  );
}
