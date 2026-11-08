import { Ban, GitMerge, Rocket, Terminal, User } from 'lucide-react';
import { Tooltip } from '../shell/Tooltip';
import type { Tiles as TilesData } from './derive';

const ICON = { size: 15, 'aria-hidden': true } as const;

/** The five tiles of the Inbox and the Overview. */
export function Tiles({ tiles, stale = false }: { tiles: TilesData; stale?: boolean }): JSX.Element {
  const d = tiles.lastDeploy;
  const deployState = d ? (d.ok === true ? 'ok' : d.ok === false ? 'failed' : 'unknown') : null;
  return (
    <div className={`kpi-strip${stale ? ' stale' : ''}`} data-testid="tiles" data-stale={stale ? 'true' : undefined}>
      <Tooltip content={`${tiles.waitingOnYou}: items in Needs you that wait on your answer`}>
        <div className={`kpi-tile${tiles.waitingOnYou > 0 ? ' urgent' : ''}`} tabIndex={0}>
          <span className="kpi-label"><User {...ICON} />Waiting on you</span>
          <span className="kpi-num accent" data-testid="tile-waiting">{tiles.waitingOnYou}</span>
        </div>
      </Tooltip>
      <Tooltip content={`${tiles.blockedMerges}: PRs with a failed required check or blocked in the queue`}>
        <div className={`kpi-tile${tiles.blockedMerges > 0 ? ' danger' : ''}`} tabIndex={0}>
          <span className="kpi-label"><Ban {...ICON} />Blocked merges</span>
          <span className="kpi-num bad" data-testid="tile-blocked">{tiles.blockedMerges}</span>
        </div>
      </Tooltip>
      <Tooltip content={`${tiles.inQueue}: PRs in the merge queue`}>
        <div className="kpi-tile" tabIndex={0}>
          <span className="kpi-label"><GitMerge {...ICON} />In merge queue</span>
          <span className="kpi-num" data-testid="tile-queue">{tiles.inQueue}</span>
        </div>
      </Tooltip>
      <Tooltip content={`${tiles.workingSessions}: sessions that are working now`}>
        <div className="kpi-tile" tabIndex={0}>
          <span className="kpi-label"><Terminal {...ICON} />Working sessions</span>
          <span className="kpi-num" data-testid="tile-working">{tiles.workingSessions}</span>
        </div>
      </Tooltip>
      <Tooltip content={d ? `Last prod deploy: ${d.label}. ${d.sub}. State: ${deployState}` : 'No prod deploy is known yet'}>
        <div className="kpi-tile deploy" tabIndex={0}>
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
      </Tooltip>
    </div>
  );
}
