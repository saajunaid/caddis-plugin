---
description: Define the words this project invented, in one place — .caddis/kb/GLOSSARY.md
---

# /glossary — define what this project coined

Every project invents vocabulary out of ordinary English, and those are the most dangerous words
in the codebase: a reader who guesses from the plain word gets it wrong and never finds out.
caddis itself coined `pool`, `relay`, `drift`, `parking-lot` — and its own glossary went five and
a half months without mentioning any of them, because nothing measured the gap.

Your job is the half a script cannot do: **write what the words mean here.**

## Step 1 — get the candidates

```
python <caddis-plugin-root>/scripts/caddis_glossary.py
```

It ranks the words this repo says often that plain English does not, and marks which already
have an entry. `--scaffold` creates `.caddis/kb/GLOSSARY.md` if it is missing.

It is a **suggester, not an oracle**. It is good on an application repo — run against a kanban
tool it proposed `board`, `lane`, `card` at the top — and noisier on a repo whose docs are ABOUT
software, where words like `protocol` are both ordinary and genuinely overloaded. Expect to
discard some suggestions. That is the intended cost: a false positive wastes three seconds, a
missing term stays undefined forever.

If the script is not available, read the repo yourself and look for the same thing.

## Step 2 — apply the admission test to each candidate

A term belongs **only if its meaning here is distinct enough from its ordinary technical sense
that a newcomer would misread it.**

- `commit`, `branch`, `endpoint` — **no**. The ordinary meaning is correct.
- A word the team bent to its own purpose — **yes**. That is the whole point.

Discard the rest without comment. A padded glossary is skimmed and then ignored.

## Step 3 — write each definition from the CODE, not from the word

Read where the term is actually used before defining it. A definition that restates the word
teaches nothing, and a wrong one is worse than a gap because it is believed.

Each row gets three things:

| Column | What goes in it |
|---|---|
| **Term** | The canonical spelling. Pick one and stop using the others. |
| **Definition** | What it means HERE, and — where it helps — why the ordinary reading misleads. Say the thing a newcomer would get wrong. |
| **DO NOT USE** | The synonyms actually causing confusion in this repo. Leave blank rather than inventing some. |

**A worked example ships with caddis.** `CADDIS-GLOSSARY.md` at the plugin root defines caddis's
own coined vocabulary the same way — read a few entries before writing yours. It is caddis's
words, not this project's: never copy its terms into a project glossary.

Good: *"pool — the single source of every shipped resource, in `.github/`. Everything installed is EXPORTED from it; nothing is authored in a bundle."*

Bad: *"pool — a pool of resources."*

## Step 4 — flag what is still dirty

Fill the **Flagged ambiguities** section with the words that remain overloaded. This is the part
people skip and it is the most valuable part, because a glossary that hides its own dirt starts
lying.

Look for a term used in several incompatible senses. In caddis, `gate` is defined as one thing
and used as at least twelve — exit gate, quality gate, evidence gate, privacy gate. The honest
move is to name the overload and recommend the two-word form, not to pick a winner by fiat.

Also flag a term whose canonical spelling the code itself contradicts. Do not "fix" either side
when both are load-bearing; document the split and where each applies.

## Step 5 — report

Say how many terms you added, how many candidates you rejected and roughly why, and what you
flagged as ambiguous. If you found nothing worth adding, say that — it is a real answer, and
better than padding the file to look productive.

## Keeping it honest

Re-run `caddis_glossary.py --check` later. It exits 1 when a frequent term has no entry. It is
**advisory**: a project may reasonably decide a common word needs no definition, and a gate that
cannot be satisfied gets bypassed rather than obeyed.

Do not enforce the DO-NOT-USE column by grepping. Most banned synonyms are ordinary English —
"step", "block", "refuse" — and a check that cries wolf gets deleted, leaving no check at all.
