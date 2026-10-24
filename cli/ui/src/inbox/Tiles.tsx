import { Ban, GitMerge, Rocket, Terminal, User } from 'lucide-react';
import type { Tiles as TilesData } from './derive';

const ICON = { size: 15, 'aria-hidden': true } as const;

/** The five tiles of the Inbox and the Overview. */
export function Tiles({ tiles, stale = false }: { tiles: TilesData; stale?: boolean }): JSX.Element {
  const d = tiles.lastDeploy;
  return (
    <div className={`kpi-strip${stale ? ' stale' : ''}`} data-testid="tiles" data-stale={stale ? 'true' : undefined}>
      <div className={`kpi-tile${tiles.waitingOnYou > 0 ? ' urgent' : ''}`}>
        <span className="kpi-label"><User {...ICON} />Waiting on you</span>
        <span className="kpi-num accent" data-testid="tile-waiting">{tiles.waitingOnYou}</span>
      </div>
      <div className={`kpi-tile${tiles.blockedMerges > 0 ? ' danger' : ''}`}>
        <span className="kpi-label"><Ban {...ICON} />Blocked merges</span>
        <span className="kpi-num bad" data-testid="tile-blocked">{tiles.blockedMerges}</span>
      </div>
      <div className="kpi-tile">
        <span className="kpi-label"><GitMerge {...ICON} />In merge queue</span>
        <span className="kpi-num" data-testid="tile-queue">{tiles.inQueue}</span>
      </div>
      <div className="kpi-tile">
        <span className="kpi-label"><Terminal {...ICON} />Working sessions</span>
        <span className="kpi-num" data-testid="tile-working">{tiles.workingSessions}</span>
      </div>
      <div className="kpi-tile deploy">
        <span className="kpi-label"><Rocket {...ICON} />Last prod deploy</span>
        {d ? (
          <>
            <span className={`kpi-val ${d.ok === true ? 'tone-good' : d.ok === false ? 'tone-bad' : ''}`}>{d.label}</span>
            <span className="kpi-sub tone-muted">{d.sub}</span>
          </>
        ) : (
          <span className="kpi-val tone-muted">No deploy yet</span>
        )}
      </div>
    </div>
  );
}
