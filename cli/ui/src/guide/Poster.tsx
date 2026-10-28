import { useMemo, useState } from 'react';
import markSvg from '../brand/mark.svg?raw';
import { guideHref } from '../shell/route';
import { MindMap } from './MindMap';
import { anchorId, type Guide } from './model';
import { posterModel } from './poster';

const MARK_HTML = markSvg.replace('<svg ', '<svg class="caddis-mark-build" ');

export type PosterMode = 'workflow' | 'mind';
export const POSTER_MODE_KEY = 'caddis.hub.posterMode';

function readPosterMode(): PosterMode {
  try {
    const v = window.localStorage.getItem(POSTER_MODE_KEY);
    return v === 'mind' ? 'mind' : 'workflow';
  } catch {
    return 'workflow';
  }
}

function writePosterMode(next: PosterMode): void {
  try {
    window.localStorage.setItem(POSTER_MODE_KEY, next);
  } catch {
    /* ignore */
  }
}

export function Poster({ guide }: { guide: Guide }): JSX.Element {
  const [mode, setMode] = useState<PosterMode>(() => readPosterMode());
  const model = useMemo(() => posterModel(guide), [guide]);

  const switchMode = (next: PosterMode): void => {
    setMode(next);
    writePosterMode(next);
  };

  return (
    <div className="gp" data-testid="guide-poster">
      <div className="gp-head">
        <div className="gp-head-left">
          <span
            className="guide-mark"
            aria-hidden="true"
            dangerouslySetInnerHTML={{ __html: MARK_HTML }}
          />
          <div>
            <h2 className="gp-title">caddis at a glance</h2>
            <p className="gp-counts">
              {`${model.version} · ${model.counts.commands} commands · ${model.counts.agents} agents · ${model.counts.skills} skills · ${model.counts.hooks} hooks`}
            </p>
          </div>
        </div>
        <div className="gp-switch" role="group" aria-label="Poster view">
          <button
            type="button"
            aria-pressed={mode === 'workflow'}
            onClick={() => switchMode('workflow')}
          >
            Workflow
          </button>
          <button
            type="button"
            aria-pressed={mode === 'mind'}
            onClick={() => switchMode('mind')}
          >
            Mind map
          </button>
        </div>
        <button
          type="button"
          className="gp-print"
          onClick={() => window.print()}
        >
          Print
        </button>
      </div>

      <div className={mode === 'workflow' ? 'gp-workflow' : 'gp-workflow gp-hidden'}>
        <div className="gp-flow">
          {model.flow.map((stage, i) => (
            <div key={stage.id} className="gp-stage">
              <h3>
                <span className="gp-step">{i + 1}</span>
                <span>{stage.label}</span>
              </h3>
              <div className="gp-chips">
                {stage.commands.map((item) => (
                  <a
                    key={item.name}
                    className={item.daily ? 'gp-chip is-daily' : 'gp-chip'}
                    href={guideHref('details', item.anchor)}
                    title={item.blurb}
                  >
                    /{item.name}
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="gp-bands">
          {model.bands.map((stage) => (
            <div key={stage.id} className="gp-band">
              <h3>{stage.label}</h3>
              <div className="gp-chips">
                {stage.commands.map((item) => (
                  <a
                    key={item.name}
                    className={item.daily ? 'gp-chip is-daily' : 'gp-chip'}
                    href={guideHref('details', item.anchor)}
                    title={item.blurb}
                  >
                    /{item.name}
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="gp-foot">
          <div className="gp-card">
            <h3>Agents</h3>
            <h4 className="gp-sub">Read only</h4>
            <div className="gp-chips">
              {model.agentsReadOnly.map((a) => (
                <a
                  key={a.name}
                  className="gp-chip"
                  href={guideHref('details', a.anchor)}
                  title={a.blurb}
                >
                  {a.name}
                </a>
              ))}
            </div>
            <h4 className="gp-sub">Writes files</h4>
            <div className="gp-chips">
              {model.agentsWrite.map((a) => (
                <a
                  key={a.name}
                  className="gp-chip"
                  href={guideHref('details', a.anchor)}
                  title={a.blurb}
                >
                  {a.name}
                </a>
              ))}
            </div>
          </div>

          <div className="gp-card">
            <h3>Skills</h3>
            <div className="gp-chips">
              {model.skillCategories.map((c) => (
                <a
                  key={c.name}
                  className="gp-chip"
                  href={guideHref('details', c.anchor)}
                >
                  {c.name} · {c.count}
                </a>
              ))}
            </div>
          </div>

          <div className="gp-card">
            <h3>Hooks</h3>
            <div className="gp-hooks">
              {model.hooks.map((h) => (
                <div key={h.event} className="gp-hook-line">
                  <a
                    className="gp-chip"
                    href={guideHref('details', anchorId('hook', h.event))}
                  >
                    {h.event} · {h.count}
                  </a>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className={mode === 'mind' ? 'gp-map-wrap' : 'gp-map-wrap gp-hidden'}>
        <MindMap model={model} />
      </div>
    </div>
  );
}
