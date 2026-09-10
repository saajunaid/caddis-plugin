---
description: "Claims in a written deliverable — do not hedge when the check is one query away, and never record someone else's hedge as a fact"
applyTo: "**/*.md"
priority: 120
---

# Claims in a document

Applies whenever you write or update a Markdown deliverable — a plan, a handover, a KB note, a
PRD, a review, a parking-lot item, a README.

## Before you write "probably", ask what the check would cost

**A hedge is a cost transferred to whoever reads next.** It is only worth transferring when the
check is genuinely expensive. One query, one `grep`, one file read — do it and write the answer.

Save the hedge for what actually cannot be settled from here, and then **say why it cannot**.
"Unknown — the host is unreachable from this network" is useful. "Probably migration 011" is not.

## Never record someone else's hedge as a fact

If a source says "most likely X", you may write "the previous session believed X, unverified" or
you may go and check. You may **not** write "X".

**A hedge recorded as a fact is worth less than no claim at all** — it reads as settled, so nobody
checks it again.

## The incident that earned this

2026-09-08, two sessions handing work between them.

| Who | What they did |
|---|---|
| The writer | Said the dead `Running` rows were *"most likely migration 011 landing"* |
| The reader | Wrote **"Migration 011 landed"** into the relay doc |

Neither was true: those columns do not exist, and the mechanism is still unknown. The writer's own
words afterwards — *"a hedge is what you write when checking is expensive. It was not expensive —
one query settled it, and I ran that query twenty minutes later anyway."*

**Both halves are faults. The writer's is the fixable one**, because it removes the hazard instead
of asking every later reader to handle it carefully.

## What this is not

It is not a ban on uncertainty. It is a rule about *cheap* uncertainty. A document full of false
confidence is worse than one that marks what it does not know — the point is to stop marking
things unknown when finding out takes ten seconds.
