import { Clock, Monitor, Moon, Pause, Play, Sun } from 'lucide-react';
import type { HubState } from '../types';
import { dataAgeText, clockText, quotaLow, quotaLowest } from './format';
import { MOTION_CHOICES, type MotionChoice } from './motion';
import { SpendBlock } from './Ring';
import { THEME_CHOICES, type ThemeChoice } from './theme';

const ICON = { dark: Moon, light: Sun, system: Monitor } as const;
const MOTION_ICON = { on: Play, off: Pause } as const;
const MOTION_LABEL = { on: 'motion', off: 'still' } as const;

interface Props {
  state: HubState | null;
  nowMs: number;
  theme: ThemeChoice;
  onTheme: (t: ThemeChoice) => void;
  motion: MotionChoice;
  onMotion: (m: MotionChoice) => void;
}

export function Footer({ state, nowMs, theme, onTheme, motion, onMotion }: Props): JSX.Element {
  const v = state?.versions;
  const quota = quotaLow(state);
  const left = quotaLowest(state);
  return (
    <footer className="sidebar-footer">
      <div className="footer-card">
        <SpendBlock slot={state?.spend} size={36} />
        <div className="updated-line">
          <Clock size={13} aria-hidden="true" />
          <span data-testid="data-age">{state ? dataAgeText(state.generated_at, nowMs) : 'Waiting for data'}</span>
        </div>
        {left && !quota && (
          <div className="quota-line mono" data-testid="quota">
            GitHub quota {left.remaining} left ({left.account})
          </div>
        )}
        {quota && (
          <div className="quota-low" data-testid="quota-low" role="status">
            GitHub quota low: {quota.remaining} left ({quota.account})
            {quota.resetAt ? `, resets ${clockText(quota.resetAt)}` : ''}. Polling slows.
          </div>
        )}
        {v && (
          <div className="versions mono">
            <span className="versions-item">hub {v.hub}</span>
            <span className="versions-item">pool {v.pool ?? '-'}</span>
            <span className="versions-item">plugin {v.plugin ?? '-'}</span>
          </div>
        )}
        <div className="footer-toggles">
          <div className="theme-switch" role="group" aria-label="Theme">
            {THEME_CHOICES.map((c) => {
              const Icon = ICON[c];
              return (
                <button key={c} type="button" className={`theme-btn${theme === c ? ' active' : ''}`} aria-pressed={theme === c} title={c} onClick={() => onTheme(c)}>
                  <Icon size={14} aria-hidden="true" />
                  <span>{c}</span>
                </button>
              );
            })}
          </div>
          <div className="theme-switch" role="group" aria-label="Motion">
            {MOTION_CHOICES.map((m) => {
              const Icon = MOTION_ICON[m];
              return (
                <button
                  key={m}
                  type="button"
                  className={`theme-btn${motion === m ? ' active' : ''}`}
                  aria-pressed={motion === m}
                  title={m === 'on' ? 'Animations on' : 'Animations off'}
                  onClick={() => onMotion(m)}
                >
                  <Icon size={14} aria-hidden="true" />
                  <span>{MOTION_LABEL[m]}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </footer>
  );
}
