import { FolderPlus, Terminal } from 'lucide-react';

export const ADD_FOLDER_REASON = 'Start a session in the folder: the hub adds it.';

/** The first-run page: no repo is known yet. "Add a folder" is not a v1 action (R42), so it stays disabled. */
export function FirstRun(): JSX.Element {
  return (
    <section className="first-run" data-testid="first-run" aria-label="Get started">
      <h2>No repos yet</h2>
      <p>
        <Terminal size={16} aria-hidden="true" /> Start a Claude Code session in a repo. The hub finds it by itself.
      </p>
      <p>Or add a folder. The hub checks that it is a git repo.</p>
      <button type="button" className="btn" disabled title={ADD_FOLDER_REASON} data-testid="add-folder">
        <FolderPlus size={16} aria-hidden="true" />
        Add a folder
      </button>
      <span className="first-run-reason"> {ADD_FOLDER_REASON}</span>
    </section>
  );
}
