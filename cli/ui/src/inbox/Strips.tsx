import { Check } from 'lucide-react';
import type { HubState } from '../types';
import { roadmapStrip, shippedList } from './strip';

/** Below the Inbox: roadmap progress and the recent merges. Nothing shows when both are empty. */
export function Strips({ state, nowMs }: { state: HubState; nowMs: number }): JSX.Element | null {
  const roadmaps = roadmapStrip(state);
  const ships = shippedList(state, nowMs);
  if (roadmaps.length === 0 && ships.length === 0) return null;
  return (
    <section className="inbox-strips" aria-label="Roadmaps and recent ships">
      {roadmaps.length > 0 && (
        <div className="strip-card" data-testid="strip-roadmaps">
          <h2 className="strip-title">Roadmaps</h2>
          {roadmaps.map((r) => (
            <div key={r.key} className="strip-rm">
              <div className="strip-rm-head">
                <span className="strip-rm-name">
                  <a href={r.href}>{r.slug}</a> <span className="mono strip-repo">{r.repo}</span>
                </span>
                <span className="strip-rm-label">{r.label}</span>
              </div>
              <div className="seg-bar">
                {r.segs.map((s) => (
                  <span key={s.id} className={`seg seg-${s.tone}`} title={`${s.id}: ${s.tone}`} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      {ships.length > 0 && (
        <div className="strip-card strip-ships" data-testid="strip-shipped">
          <h2 className="strip-title">Shipped</h2>
          {ships.map((s) => (
            <div key={s.key} className="ship-row">
              <Check size={14} strokeWidth={2.6} aria-hidden="true" className="ship-check" />
              <span className="mono ship-repo">{s.repo}</span>
              <span className="ship-title">
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noreferrer noopener">
                    {s.title}
                  </a>
                ) : (
                  s.title
                )}
              </span>
              <span className="ship-age">{s.age.replace(/ ago$/, '')}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
