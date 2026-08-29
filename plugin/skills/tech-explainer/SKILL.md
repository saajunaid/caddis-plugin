---
name: tech-explainer
context: fork
description: >-
  Write a plain-language technical explainer for a smart reader who did NOT do the investigation — a
  manager, an infra colleague, a stakeholder, the person whose recommendation you are answering.
  Layered Mermaid diagrams that rank causes by SIZE OF EFFECT, a controlled-vocabulary table,
  Simplified Technical English, published withdrawn results, and questions back to the reader. Use
  this skill whenever the user says "explain this to X", "explainer", "write this up for someone
  non-technical", "plain English", "simplified technical english", "STE", "explain our findings",
  "write up the benchmark results", "answer my manager's recommendations", "why is it slow — document
  it", "make a doc with diagrams explaining the stack", or is about to summarise an investigation, a
  benchmark, a postmortem, an architecture, or a disagreement for a reader who will not read the raw
  data. NOT for handing off work to be BUILT by a vendor or another team (use explainer-doc for that —
  it produces an actionable spec); NOT for READMEs or API docs (use technical-writing). This one
  produces UNDERSTANDING: the reader must finish able to argue with you on the merits.
---

# tech-explainer — make a stranger understand, and able to push back

The reader is intelligent but was not in the room. They did not watch the tests, they will not read
the raw report, and they have their own opinion about what you should do. If you hand them the
findings compressed, every conclusion looks like an assertion, and the conversation becomes
credentials against credentials.

**The job is not to summarise. The job is to transfer enough of the reasoning that the reader can
disagree with you correctly.** A reader who finishes and says "I still think it's the wrapper, and
here's why your 3x number is wrong" is a success. A reader who nods and remembers nothing is a
failure, even if they agreed.

## What this skill gives you

| File                        | Use it for                                                                  |
| --------------------------- | --------------------------------------------------------------------------- |
| `assets/skeleton.md`        | **Start here.** The fill-in document. Copy it, then delete what has nothing to say. |
| `references/diagrams.md`    | Copy-paste Mermaid for all six patterns, plus the syntax that bites.        |
| `references/language.md`    | Full STE rules, the rewrite table, and the mechanical rewrite pass.         |

## When this is NOT the right skill

- The reader must **build** something from the document → `explainer-doc`. That skill produces an
  actionable spec (DDL, queries, acceptance criteria). This one produces understanding.
- The reader already lived through the investigation → `technical-writing` or a plain summary. The
  vocabulary table and STE discipline are overhead they don't need.
- It's a README, API reference, or runbook → `technical-writing`.

The tell for *this* skill: **the reader will form or change an opinion**, and you need that opinion
to be based on the numbers rather than on trust.

## The central move — rank the layers by size of effect

This is the single technique that makes the document work, and it is what most explainers get wrong.

An architecture diagram shows **what exists**. It is the natural thing to draw and it is nearly
useless here, because the reader's real question is not "what is the shape of this system" — it is
**"what should we change?"** So draw the same stack, but label every layer with **the magnitude of
its effect on the outcome**:

```
LAYER 1 — The model — LARGEST EFFECT — about 3x
LAYER 2 — The engine — MEDIUM EFFECT — tens of percent
LAYER 3 — The program — SMALL EFFECT — under 5%
LAYER 4 — The operating system — NO EFFECT
```

Now the reader who came in convinced that swapping the program would fix everything can see, without
being contradicted, that they were aiming at the 5% layer. **The disagreement becomes arithmetic.**
That is worth more than any paragraph of argument, because arithmetic is something they can check
and you cannot fake.

Rules for this diagram:

- **Order the layers by effect size, largest first** — not by where they sit in the stack, and not by
  the order you investigated them.
- **Every layer carries a number or an honest "no effect"**, plus the one-line reason. A layer with no
  measurement is a layer you are guessing about; say "not measured" rather than inventing a rank.
- **Include the layer the reader is about to optimise, even if it ranks last.** Leaving it out looks
  evasive. Ranking it last with a measured number is the whole argument.
- **Say how to read it.** One line under the diagram: *"If we change the program, we gain a few
  percent. If we change the model, we gain about 3 times. Layer 1 is where the work must go."*

If your subject has no natural layers, the same move still applies: rank the candidate causes by
their measured contribution, and call them causes rather than layers. The stack is a convenience; the
ranking is the point. It transfers to any "why is it slow / expensive / wrong" question — the causes
of an ETL's runtime, the sources of a cloud bill, the contributors to a defect rate.

**An attribution number must carry its method.** "The N+1 query is 85% of the p99" is the sentence
the whole document rests on, and share-of-total figures are where this kind of analysis rots: they
get produced by one tool, quoted onward, and nobody remembers whether it was mean or p99, warm or
cold, one endpoint or all of them. Say how the share was obtained, in the same breath — *"85% of p99,
from 12,000 spans over 24 hours, attributed by span duration"*. If you cannot say how, rank it
qualitatively and mark it unmeasured rather than putting a false number on the diagram.

## Simplified Technical English — the language discipline

STE is not dumbing down. It is removing every sentence that can be read two ways, so a reader who is
expert in a *different* field never has to guess. Announce it in the header so the terseness reads as
courtesy rather than curtness:

> **Written in Simplified Technical English.** Short sentences. One idea per sentence.

Six rules cover most of it. Full rules and before/after rewrites: `references/language.md`.

1. **One idea per sentence.** Aim under 20 words. Split on "and", "but", "which", ";".
2. **One word, one meaning.** Fix the term in the vocabulary table (§2), then never use a synonym for
   it. "Engine" stays "engine" — never "backend", "runtime", or "inference layer".
3. **Active voice, and name the actor.** "We withdrew the result", not "the result was withdrawn".
4. **No idiom, no metaphor, no hedging.** Not "the low-hanging fruit", not "it seems likely that".
   If you are unsure, say the size of your uncertainty: "we measured this once, on a test prompt".
5. **Every number carries its unit and its basis.** "2,373 output tokens per summary, measured from
   `gpt-4o`" — not "about 2.4k tokens".
6. **Never open a paragraph with a pronoun standing in for the previous paragraph.** The reader
   skims and lands mid-document; name the subject again. ("This is the most important diagram in
   this document" is fine — "this" points at the thing directly below it, not at prose above.)

## The shape — sections in this order

The order is load-bearing: the reader must be able to stop at any section and have gained something
complete. Not every document needs all fifteen. The **bold** slots are the ones that make it *this*
kind of document; drop the others when they have nothing to say.

| §   | Slot                              | What it does                                                                                                                    |
| --- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| —   | **Header**                        | Title, `**Audience:**` by name, and the STE announcement. Naming the reader changes how the whole document reads.                |
| 1   | **Why this document exists**      | Numbered list of the questions this answers. Then route the reader's own question: *"Section 5 answers the LM Studio question."* |
| 2   | **Words used in this document**   | Controlled vocabulary table. One meaning only. This is what lets the rest be short.                                             |
| 3   | What we are building              | One left-to-right flowchart of the real pipeline, plus the physical facts (hardware, OS, versions).                              |
| 4   | **The goal, in numbers**          | Target / measured / gap, in a table, with the three key rows in bold. If there is no gap, say what "good" is.                    |
| 5   | The layer stack                   | What sits on what, and which layers are cheap to change. Answer the reader's specific question here if they asked one.           |
| 6   | Why the work took so long         | The results you **withdrew**, and what caught each one. See below — this section buys more credibility than any other.           |
| 7   | Where the time (or cost) goes     | A proportion chart with the sample count. Redirects effort before anyone argues about it.                                        |
| 8   | **What limits the result**        | The ranked-layer diagram. The most important diagram in the document. Say so, and say how to read it.                            |
| 9   | The recommendations we checked    | One row per claim: recommendation / verdict / evidence. Then a **"Where the advice is right"** subsection.                       |
| 10  | What the constraint costs         | The forced choice (a platform, a vendor, a deadline) — what it costs, and what it genuinely gives back.                          |
| 11  | **What we do next**               | Ordered steps as a flowchart. Name which step matters most. Then list the measurement gaps still open.                           |
| 12  | Questions for \<reader\>          | Real questions only. This converts a verdict into a conversation.                                                                |
| 13  | **Summary in five lines**         | Five numbered sentences. Someone will read only this. Make it survivable alone.                                                  |
| —   | **Related documents**             | Table: document → what it holds. This is what lets §1–13 stay short without hiding anything.                                     |

Rename the slots to fit the domain — a security review, a cost analysis, and a latency investigation
will all name §3–§10 differently. Keep the order and the intent.

### When a slot does not fit

Most explainers hit two or three of these. Substituting is right; padding the slot with invented
content is not, and forcing a section you have nothing for is how the document starts sounding
false.

| Situation                                            | What to do                                                                                                                                                                                            |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **§4 — no target exists**                            | Retitle it "The result, in numbers" and make the missing target the finding: *"We have no agreed p99 target. That is the first thing to fix."* A gap you cannot size is still worth naming.            |
| **§5 duplicates §8** (few causes, one stack)         | Collapse. Make §5 a table with a column §8 lacks — usually **cost to change** or **who owns it** — and let §8 carry the only stack diagram. Two near-identical diagrams teach the reader nothing twice. |
| **§6 — nothing was withdrawn**                       | Do not invent a retraction. Substitute the assumptions the argument rests on, plus what would falsify each. Same function: it shows the reader where to attack.                                        |
| **§9 — no formal list of recommendations**           | The reader still has a belief. Turn it into a claims-checked table: *the claim as they would state it* / verdict / evidence. "It's just copying data" is a claim; check it like one.                    |
| **No independent external number to anchor against** | Say so once and move on. A stated absence costs nothing; a fabricated comparison costs the document.                                                                                                   |
| **The reader has no name** ("my manager")            | Use their role in the audience line — *"Audience: the engineering manager"* — and leave a visible placeholder. Never invent a name.                                                                     |
| **The prompt is the only source**                    | Say so in §1 and label every number by origin: measured / calculated / assumed. See process step 2.                                                                                                    |

### When to stop

Section count follows the evidence, not the template. Four numbers and one conclusion is a six-section
document; a three-week investigation with retractions is a fifteen-section document. If a section
would exist only because the table lists it, cut it — a short explainer that a manager finishes beats
a complete one they abandon at §7.

The load-bearing minimum is: the audience line, §2, §8, §13, and the related-documents table.

## The moves that carry the document

**Lead every section with the bolded short answer.** The reader is looking for the answer to one
question. Give it in the first line, in bold, then spend the section earning it:

> **Short answer: we do not have LM Studio installed. But we already run the engine that is inside
> LM Studio.**

**Publish what you withdrew.** List the results you reported and later retracted, each with the cause
and how it was caught. This feels like confessing and it is actually the strongest section in the
document: it explains why the work took three weeks, it proves the surviving numbers were checked the
same way, and it inoculates you against the next person who finds an error. End with the lesson in
one line — *"a benchmark that gives a believable number is not therefore correct."*

**Steelman the person you are answering.** Before refuting a recommendation, write the subsection
where they are right, and mean it. *"The review is correct that the GPU is not fully used. We confirmed
this with arithmetic."* Then: *"The instinct behind the advice is right. The cause is different from
the cause given."* Nobody accepts a correction from someone who did not first understand them.

**Route each wrong assumption to its real cause, and it is usually not the reader.** When someone
recommends a fix you have already applied, the honest framing is almost never "they were wrong" — it
is that nobody told them. Write it that way: *"The database has been on NVMe since March. That is not
recorded anywhere the infra team can see, which is our gap to close, not a wrong call."* This is the
same instinct as the steelman, applied to facts rather than judgement, and it does real work in a
document that answers someone senior: it separates **the recommendation was reasonable given what
they knew** from **the recommendation is what we should do**, which is the only distinction that
lets a senior reader change position without losing anything. Look for it every time a verdict comes
out "already done" or "does not apply here".

**Show the arithmetic in a bare code block.** When a conclusion rests on a calculation, print it so
the reader can redo it in their head:

```
GPU memory speed                 3,900 GB per second
Data read per token              2.65 GB
Theoretical maximum              1,470 tokens per second
Measured                         114 to 316 tokens per second   (8% to 21%)
```

A number the reader can re-derive is a number they own. A number they must accept is one they will
challenge later, at a worse time.

**Anchor against an independent external result, when one exists.** "Are we misconfigured?" is
answerable only by comparison. Find someone else's published number on comparable kit, put it in a
two-row table beside yours, and state the conclusion plainly. This turns a defensive claim into a
measurement. If no comparable number exists, say that in one line and move on — never assemble a
lookalike from a different workload to fill the slot.

**Admit the gaps you did not close.** Name what you never measured directly and what you would need
to do it. Two or three lines. A document with no admitted gaps reads as marketing.

**Diagrams for shape, tables for detail, prose only for judgement.** If a table says it better, delete
the diagram. The count is not the test — the test is that each diagram answers a question no other
one answers. The source explainer carries eight across thirteen sections and none is redundant; a
six-section explainer with four near-identical stack diagrams is over-drawn.

## Diagram vocabulary

Keep to a small, repeated set of Mermaid shapes — the document reads as one voice because the same
four patterns recur. Copy-paste versions with the syntax details (bold inside nodes, dotted
"hypothetical" arrows, line breaks, pie charts): `references/diagrams.md`.

| Pattern                            | Use for                                        |
| ---------------------------------- | ---------------------------------------------- |
| `flowchart LR`                     | The pipeline. Input → work → output.           |
| `flowchart TB` with `subgraph`s    | The layer stack — §5, and the ranked §8.       |
| `flowchart LR` with a decision node | A loop or a check procedure.                    |
| `pie showData`                     | Where the time/cost goes. Give the run or N.   |

Check every diagram before shipping: paste it into `mermaid.live`, or read it against the syntax
table at the end of `references/diagrams.md`. A broken Mermaid block renders as raw source and costs
more credibility than the diagram was worth.

## Process

1. **Name the reader and their question.** Ask if it is not obvious. "Explain the benchmark" is not
   enough — you need *who* and *what they currently believe*, because §8's ranking exists to meet a
   specific wrong (or right) belief. If they already have full context, stop and use a plain summary.
2. **Read the source material yourself.** The raw report, the measurement logs, the plan, the thread
   you are answering. Do not write an explainer from a summary — the explainer is the place where
   soft numbers get caught, and you cannot catch them at second hand. **If no source exists and the
   request itself is all you have**, that is workable but must be visible: say in §1 that the numbers
   come from the requester, and tag every figure in the document `(measured)`, `(calculated)` — with
   the arithmetic shown — or `(assumed)`. The tags cost a few words and they are what stop your
   inference being quoted back later as someone's measurement.
3. **Build §8 first.** List every candidate cause, attach its measured effect size, and sort. If you
   cannot rank them, you do not yet understand the system well enough to explain it — go measure, or
   say explicitly which layers are unranked and why.
4. **Write §2, the vocabulary, second.** Every term you fix here makes the following sections shorter.
5. **Copy `assets/skeleton.md` and fill it top to bottom**, deleting the slots that have nothing to
   say (see "When a slot does not fit"). Keep evidence beside each claim rather than in an appendix.
6. **Rewrite in STE last, as its own pass.** Split long sentences, hunt synonyms for defined terms,
   convert passive to active, attach units to bare numbers. It is a mechanical pass; do it
   mechanically. `references/language.md` has the rewrite table.
7. **Run the exit gate.**

## The exit gate

Ask all four before shipping. Each one has caught a real defect in this document type.

- **"Can the reader disagree with me on the merits?"** If every conclusion rests on "we measured it"
  with no visible number or method, they can only agree or distrust. Neither is useful.
- **"Does §8 rank the layer the reader cares about?"** If their favoured fix is missing from the
  ranked diagram, the document dodges instead of answering.
- **"Would the five-line summary survive alone?"** Someone will forward only that. Read it cold.
- **"What did I state without a basis?"** Every number needs a unit, a sample size or a measurement
  date, and a way to reproduce it. Bare numbers are where explainers rot first — they get quoted
  onward, and six weeks later nobody knows what they measured.
- **"Which section is here only because the template listed it?"** Cut it. Padding reads as padding,
  and it spends the attention you need for §8.

If the repository has a document-frontmatter convention, apply it (`type: analysis` fits this
document kind). Then add the document to the doc index if one exists.
