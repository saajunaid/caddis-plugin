import { RefreshCw } from 'lucide-react';

/** The "Sync now" action of the hub header: fetch every repo, then refresh every source. */
export function SyncButton({ syncing, onSync }: { syncing: boolean; onSync: () => void }): JSX.Element {
  return (
    <button
      type="button"
      className={`sync-btn${syncing ? ' syncing' : ''}`}
      data-testid="hub-sync-now"
      disabled={syncing}
      aria-busy={syncing}
      onClick={onSync}
    >
      <RefreshCw size={15} aria-hidden="true" />
      <span className="sync-label">{syncing ? 'Syncing…' : 'Sync now'}</span>
    </button>
  );
}
