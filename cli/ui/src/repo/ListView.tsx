import { repoId as repoIdOf, repoTabHref } from '../shell/route';
import type { RepoState } from '../types';
import { listRow, type RepoRoadmaps } from './roadmap';
import type { Variant } from './RoadmapTab';
import { Bar } from './RoadmapTimeline';

/** The site routes are `#/` and `#/roadmap/<slug>` (R63). The hub routes are repo routes. */
export const roadmapHref = (variant: Variant, id: string, slug?: string): string =>
  variant === 'site' ? (slug ? `#/roadmap/${encodeURIComponent(slug)}` : '#/') : repoTabHref(id, 'roadmap', slug);

export function ListView({ repo, m, variant }: { repo: RepoState; m: RepoRoadmaps; variant: Variant }): JSX.Element {
  const id = repoIdOf(repo);
  return (
    <div className="rm-list-view">
      {(m.errors.length > 0 || m.repoError || m.roadmaps.some((r) => r.detailError)) && (
        <div className="lane-note" data-testid="rm-errors">
          {m.repoError && <div>Could not read this repo: {m.repoError}</div>}
          {m.errors.map((e) => (
            <div key={e.slug}>
              Could not read {e.slug}: {e.error}
            </div>
          ))}
          {m.roadmaps
            .filter((r) => r.detailError)
            .map((r) => (
              <div key={r.slug}>
                Detail unavailable for {r.slug}: {r.detailError}
              </div>
            ))}
        </div>
      )}
      <ul className="flow-list rm-cards" data-testid="rm-list" aria-label="Roadmaps">
        {m.roadmaps.map((r) => {
          const row = listRow(r);
          return (
            <li key={r.slug}>
              <a className={`rm-rcard rm-card tone-${row.tone}`} data-testid="rm-card" href={roadmapHref(variant, id, r.slug)}>
                <span>
                  <strong>{row.slug}</strong> <span className="rm-sub">{row.branch ?? ''}</span>
                </span>
                <Bar done={row.phasesDone} total={row.phasesTotal} />
                <span className="rm-sub">
                  {row.milestonesDone}/{row.milestonesTotal} milestones
                </span>
                <span className="rm-dots">
                  {row.dots.map((d) => (
                    <span key={d.id} className={`rm-dot s-${d.status}`}>
                      {d.id}
                    </span>
                  ))}
                </span>
                <span className="rm-sub">
                  next: {row.next}
                  {variant === 'hub' ? ` · runner: ${row.runner}` : ''}
                  {row.gates > 0 ? ` · ${row.gates} open gate${row.gates === 1 ? '' : 's'}` : ''}
                </span>
              </a>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
