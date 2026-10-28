import { useEffect, useMemo, useState } from 'react';
import {
  SECTION_IDS,
  SECTION_TITLES,
  STAGE_ORDER,
  anchorId,
  runtimesOf,
  type Guide,
  type GuideAgent,
  type GuideCommand,
  type GuideHook,
  type GuideSkill,
  type SectionId,
} from './model';
import { blurb } from './poster';

export interface DetailsProps {
  guide: Guide;
  item: string | null;
  initialFilter?: string;
}

const STAGE_LABELS: Record<string, string> = {
  setup: 'Setup',
  plan: 'Plan',
  build: 'Build',
  review: 'Review',
  ship: 'Ship',
  continuity: 'Continuity',
  knowledge: 'Knowledge',
  other: 'Other',
};

function matchesFilter(needle: string, ...fields: (string | undefined)[]): boolean {
  if (!needle) return true;
  return fields.some((f) => f !== undefined && f.toLowerCase().includes(needle));
}

function groupCommandsByStage(commands: GuideCommand[]): [string, GuideCommand[]][] {
  const byStage = new Map<string, GuideCommand[]>();
  for (const cmd of commands) {
    const key = cmd.stage || 'other';
    const list = byStage.get(key) ?? [];
    list.push(cmd);
    byStage.set(key, list);
  }
  const ordered: [string, GuideCommand[]][] = [];
  for (const stage of STAGE_ORDER) {
    const list = byStage.get(stage);
    if (list && list.length > 0) {
      ordered.push([stage, list]);
      byStage.delete(stage);
    }
  }
  for (const [stage, list] of byStage.entries()) {
    if (list.length > 0) ordered.push([stage, list]);
  }
  return ordered;
}

function groupSkillsByCategory(skills: GuideSkill[]): [string, GuideSkill[]][] {
  const byCat = new Map<string, GuideSkill[]>();
  for (const skill of skills) {
    const key = skill.category || 'uncategorised';
    const list = byCat.get(key) ?? [];
    list.push(skill);
    byCat.set(key, list);
  }
  return Array.from(byCat.entries());
}

function SectionHeading({
  id,
  total,
  shown,
  isFiltered,
}: {
  id: SectionId;
  total: number;
  shown: number;
  isFiltered: boolean;
}): JSX.Element {
  return (
    <h2>
      {SECTION_TITLES[id]}{' '}
      <span className="guide-count" data-testid={`guide-count-${id}`}>
        {total}
      </span>
      {isFiltered && (
        <>
          {' '}
          <span className="guide-shown" data-testid={`guide-shown-${id}`}>
            {`${shown} of ${total}`}
          </span>
        </>
      )}
    </h2>
  );
}

export function Details({ guide, item, initialFilter = '' }: DetailsProps): JSX.Element {
  const [filter, setFilter] = useState(initialFilter);
  const needle = filter.trim().toLowerCase();
  const isFiltered = needle.length > 0;

  useEffect(() => {
    if (!item || typeof document === 'undefined') return;
    const el = document.getElementById(item);
    if (!el) return;
    if (el.tagName === 'DETAILS') {
      (el as HTMLDetailsElement).open = true;
    }
    const parentDetails = el.parentElement?.closest('details');
    if (parentDetails) {
      (parentDetails as HTMLDetailsElement).open = true;
    }
    if (typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'start' });
    }
    el.classList.add('is-target');
    const timer = window.setTimeout(() => {
      el.classList.remove('is-target');
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [item]);

  const jump = (id: SectionId): void => {
    if (typeof document === 'undefined') return;
    document.getElementById(`guide-${id}`)?.scrollIntoView({
      block: 'start',
      behavior:
        typeof window !== 'undefined' &&
        window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
          ? 'auto'
          : 'smooth',
    });
  };

  const commands = useMemo(
    () =>
      guide.commands.filter((c) =>
        matchesFilter(needle, c.name, c.description, c.stage)
      ),
    [guide.commands, needle]
  );

  const agents = useMemo(
    () =>
      guide.agents.filter((a: GuideAgent) =>
        matchesFilter(needle, a.name, a.description)
      ),
    [guide.agents, needle]
  );

  const skills = useMemo(
    () =>
      guide.skills.filter((s) =>
        matchesFilter(needle, s.name, s.description, s.category)
      ),
    [guide.skills, needle]
  );

  const hooks = useMemo(
    () =>
      guide.hooks.filter((h: GuideHook) =>
        matchesFilter(needle, h.event, h.matcher, h.handler)
      ),
    [guide.hooks, needle]
  );

  const commandGroups = useMemo(() => groupCommandsByStage(commands), [commands]);
  const skillGroups = useMemo(() => groupSkillsByCategory(skills), [skills]);
  const allRuntimes = useMemo(() => runtimesOf(guide), [guide]);
  const runtimes = useMemo(
    () =>
      allRuntimes.filter((r) =>
        matchesFilter(needle, r.name, ...r.kinds)
      ),
    [allRuntimes, needle]
  );

  const commandsTotal = guide.counts?.commands ?? guide.commands.length;
  const agentsTotal = guide.counts?.agents ?? guide.agents.length;
  const skillsTotal = guide.counts?.skills ?? guide.skills.length;
  const hooksTotal = guide.counts?.hooks ?? guide.hooks.length;
  const runtimesTotal = allRuntimes.length;
  const totalShown =
    commands.length + agents.length + skills.length + hooks.length + runtimes.length;

  const seenHookEvents = new Set<string>();

  return (
    <>
      <div className="guide-tools">
        <label className="guide-filter">
          <span className="guide-filter-label">Filter the guide</span>
          <input
            type="search"
            className="guide-filter-input"
            value={filter}
            placeholder="Name, purpose, stage or hook"
            onChange={(e) => setFilter(e.target.value)}
            data-testid="guide-filter"
          />
        </label>
        <nav className="guide-chips" aria-label="Guide sections">
          {SECTION_IDS.map((id) => (
            <button
              type="button"
              className="guide-jump"
              key={id}
              onClick={() => jump(id)}
            >
              {SECTION_TITLES[id]}
            </button>
          ))}
        </nav>
        <p className="guide-note">
          Invoke forms are for Claude Code. Other runtimes list the same names in their own way.
        </p>
      </div>

      {isFiltered && totalShown === 0 && (
        <p className="notice" data-testid="guide-nomatch">
          Nothing matches <code className="cmd">{filter}</code>.
        </p>
      )}

      <section className="gd-section" id="guide-commands">
        <SectionHeading
          id="commands"
          total={commandsTotal}
          shown={commands.length}
          isFiltered={isFiltered}
        />
        {commandGroups.map(([stage, entries]) => (
          <div key={stage} className="guide-group">
            <h3 className="gd-stage">{STAGE_LABELS[stage] ?? STAGE_LABELS.other ?? stage}</h3>
            {entries.map((c) => {
              const cmdId = anchorId('command', c.name);
              return (
                <details
                  key={c.name}
                  className="gd-item"
                  id={cmdId}
                  open={item === cmdId || undefined}
                  data-testid="guide-entry"
                >
                  <summary>
                    <code className="gd-name">/caddis:{c.name}</code>
                    <span className="gd-blurb">{blurb(c.description)}</span>
                    {c.daily && <span className="guide-chip good">daily</span>}
                    {c.noArgs && <span className="guide-chip">no args</span>}
                  </summary>
                  <p>{c.description}</p>
                  {c.steps.length > 0 && (
                    <ol className="gd-steps">
                      {c.steps.map(([num, title], idx) => (
                        <li key={`${num}-${idx}`}>
                          {num} {title}
                        </li>
                      ))}
                    </ol>
                  )}
                  {c.hint && <p className="gd-hint">{c.hint}</p>}
                </details>
              );
            })}
          </div>
        ))}
      </section>

      <section className="gd-section" id="guide-agents">
        <SectionHeading
          id="agents"
          total={agentsTotal}
          shown={agents.length}
          isFiltered={isFiltered}
        />
        <table className="gd-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>What it does</th>
              <th>Access</th>
              <th>Model</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.name} id={anchorId('agent', a.name)} data-testid="guide-entry">
                <td>
                  <code>{a.name}</code>
                </td>
                <td>{a.description}</td>
                <td>{a.writes ? 'writes files' : 'read only'}</td>
                <td>{a.model}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="gd-section" id="guide-skills">
        <SectionHeading
          id="skills"
          total={skillsTotal}
          shown={skills.length}
          isFiltered={isFiltered}
        />
        {skillGroups.map(([category, entries]) => {
          const catId = anchorId('skillCategory', category);
          const isOpen =
            isFiltered ||
            item === catId ||
            entries.some((s) => anchorId('skill', s.name) === item);
          return (
            <details
              key={category}
              className="gd-group"
              id={catId}
              open={isOpen || undefined}
            >
              <summary>
                {category} · {entries.length}
              </summary>
              {entries.map((s) => (
                <div
                  key={s.name}
                  className="gd-skill"
                  id={anchorId('skill', s.name)}
                  data-testid="guide-entry"
                >
                  <code>{s.name}</code>
                  {s.core && <span className="guide-chip good">core</span>}
                  <span className="gd-blurb">{blurb(s.description)}</span>
                </div>
              ))}
            </details>
          );
        })}
      </section>

      <section className="gd-section" id="guide-hooks">
        <SectionHeading
          id="hooks"
          total={hooksTotal}
          shown={hooks.length}
          isFiltered={isFiltered}
        />
        <table className="gd-table">
          <thead>
            <tr>
              <th>Event</th>
              <th>Matcher</th>
              <th>Handler</th>
            </tr>
          </thead>
          <tbody>
            {hooks.map((h, i) => {
              const isFirstForEvent = !seenHookEvents.has(h.event);
              if (isFirstForEvent) {
                seenHookEvents.add(h.event);
              }
              return (
                <tr
                  key={`${h.event}-${h.matcher}-${h.handler}-${i}`}
                  id={isFirstForEvent ? anchorId('hook', h.event) : undefined}
                  data-testid="guide-entry"
                >
                  <td>{h.event}</td>
                  <td>{h.matcher}</td>
                  <td>{h.handler}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="gd-section" id="guide-runtimes">
        <SectionHeading
          id="runtimes"
          total={runtimesTotal}
          shown={runtimes.length}
          isFiltered={isFiltered}
        />
        <p className="guide-note">
          caddis install and caddis update put these on each runtime.
        </p>
        <ul className="guide-list">
          {runtimes.map((r) => (
            <li key={r.name} className="guide-entry" data-testid="guide-entry">
              <div className="guide-entry-head">
                <span className="guide-entry-name">{r.name}</span>
              </div>
              <p className="guide-entry-purpose">{`Receives: ${r.kinds.join(', ')}`}</p>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
