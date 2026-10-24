# Edge list from an event table (SQL pattern)

Use this when the steps of each case are rows in an event table. The output is the edge list that
`scripts/edges_to_mermaid.py` reads: `from,to,count`, plus a box-count list `name,count`.

The SQL is ANSI with window functions. It runs on most SQL engines with small changes
(parameter style, date functions).

## Input shape

One row per step a case took:

| column      | meaning                                                                     |
|-------------|-----------------------------------------------------------------------------|
| `case_id`   | the unit you count: a call, an order, a ticket, a session                   |
| `step`      | the step name, in the words of the team that owns the process               |
| `step_time` | when the step started, in UTC                                               |
| `step_seq`  | a tie-breaker when two steps share one timestamp (an event id or a counter) |

## Query

```sql
-- 1. Choose the cases by their START time in the window, then take ALL their steps.
--    If you filter steps by time instead, a case that crosses the window edge loses its
--    first or last steps, and the chart shows false starts and false ends.
WITH cases AS (
    SELECT case_id
    FROM   events
    GROUP  BY case_id
    HAVING MIN(step_time) >= :window_start_utc
       AND MIN(step_time) <  :window_end_utc
),
ordered AS (
    SELECT e.case_id, e.step, e.step_time, e.step_seq,
           LAG(e.step) OVER (PARTITION BY e.case_id ORDER BY e.step_time, e.step_seq) AS prev_step
    FROM   events e
    JOIN   cases  c ON c.case_id = e.case_id
),
-- 2. Collapse consecutive repeats: A, A, B becomes A, B. A repeat is not a path.
collapsed AS (
    SELECT case_id, step, step_time, step_seq
    FROM   ordered
    WHERE  prev_step IS NULL OR prev_step <> step
),
-- 3. The next step of each step. No next step means the case ends: 'END'.
pairs AS (
    SELECT case_id,
           step AS from_step,
           COALESCE(LEAD(step) OVER (PARTITION BY case_id ORDER BY step_time, step_seq), 'END') AS to_step,
           ROW_NUMBER() OVER (PARTITION BY case_id ORDER BY step_time, step_seq) AS rn
    FROM   collapsed
)
-- 4. Count DISTINCT cases per pair: the same unit as the boxes. Add one START row per case.
--    path_count (times taken) is kept only to compare; do not draw it.
SELECT from_step AS "from", to_step AS "to",
       COUNT(DISTINCT case_id) AS "count",
       COUNT(*)                AS path_count
FROM   pairs
GROUP  BY from_step, to_step
HAVING COUNT(DISTINCT case_id) >= :min_cases
UNION ALL
SELECT 'START', from_step, COUNT(*), COUNT(*)
FROM   pairs
WHERE  rn = 1
GROUP  BY from_step
ORDER  BY 3 DESC;
```

Box counts (distinct cases per step), from the same `collapsed` set:

```sql
SELECT step AS name, COUNT(DISTINCT case_id) AS count
FROM   collapsed
GROUP  BY step;
```

## What the numbers mean

- **Draw distinct cases on the arrows, the same unit as the boxes.** `count` is
  `COUNT(DISTINCT case_id)` per pair. `path_count` (`COUNT(*)`) counts each time a path was taken,
  so a case that loops (A, B, A, B) counts twice. A business reader then sees a box of 8,538
  followed by an arrow of 8,541 and stops trusting the chart. On one measured day `COUNT(*)`
  overstated an arrow by 4%. Keep `path_count` only to compare.
- **Self-check: no arrow into or out of a box exceeds the box's distinct count.** If one does,
  the query counts occurrences, not cases. The converter warns on this when it has box counts.
- **Arrows into a box can sum to a little more than the box** when a case reaches it by two
  paths. That is correct; say so in the note under the chart.
- **`HAVING` hides small paths.** Apply the threshold to either count, but label every number on
  the chart as cases. Run the query once without it, or sum the hidden rows, so the
  note under the chart can name what is not drawn and how many cases that is. A chart that hides
  paths without saying so looks complete and is not.
- **The tie-breaker matters.** Without `step_seq`, two steps at one timestamp come out in any
  order, and `LAG`/`LEAD` give different paths on each run. Check: run the query twice and compare.
- **Time zone.** Filter in UTC. When the reader thinks in local days, convert the local day to a
  UTC window first, and put both on the chart title, for example
  `Mon 5 Oct 2026 (4 Oct 23:00 to 5 Oct 23:00 UTC)`.

## Check the edge list before you draw it

- The `START` rows add up to the number of cases in the window.
- Before the `HAVING` filter, for each step the paths in equal the paths out (with `END`
  counted as out). A gap means a filter dropped rows, or a step name differs in spelling
  between rows.
- Run the converter: its note lists every hidden path. Read that list. A large hidden total means
  the minimum is too high, or many small steps need to be merged into one named box.
