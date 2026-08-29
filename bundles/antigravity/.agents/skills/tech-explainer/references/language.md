# Simplified Technical English for explainers

Read this during the STE rewrite pass (process step 6), not while drafting. Drafting in STE from the
first word produces stilted, thin prose — write the ideas out normally, then compress them here.

## Contents

- [Why STE, and what it is not](#why-ste-and-what-it-is-not)
- [The rules](#the-rules)
- [The rewrite table](#the-rewrite-table)
- [Building the vocabulary table (§2)](#building-the-vocabulary-table-2)
- [Numbers](#numbers)
- [Words to delete on sight](#words-to-delete-on-sight)
- [The mechanical pass](#the-mechanical-pass)

## Why STE, and what it is not

Simplified Technical English comes from aerospace maintenance manuals, where a misread sentence
grounds an aircraft. It constrains grammar and vocabulary so that a sentence has exactly one reading.

It is **not** writing for a beginner. Your reader may be more senior than you. They are expert in a
*different* area, and they are reading fast. STE removes the work of guessing which of two readings
you meant, so their attention goes to your argument instead of your syntax.

A side effect worth knowing: STE makes weak claims obvious. "Performance was somewhat impacted by
the configuration" survives normal prose. Rewritten as "the configuration made X slower by Y" it
either gets a number or gets deleted. **The rewrite pass is also a truth pass.**

## The rules

1. **One idea per sentence.** Target under 20 words. Split on `and`, `but`, `which`, `;`, and any
   comma joining two independent clauses.
2. **One word, one meaning.** Fix each term in §2 and use only that term. Synonym variation is good
   literary style and bad technical style — the reader cannot tell whether "engine", "runtime", and
   "backend" are three things or one.
3. **One meaning, one word.** The converse: never use a defined term for anything else. If "program"
   means the installable wrapper, do not also call a Python script a "program".
4. **Active voice, actor named.** "We withdrew the result" > "the result was withdrawn". Passive
   hides who did it, and in an investigation write-up that is exactly the information at stake.
5. **Present tense for what is true, past tense for what was measured.** "Decode is 91.6% of the
   time" (a property). "We measured 223 samples" (an event).
6. **No idiom, no metaphor, no humour, no rhetorical questions.** These are the constructs that
   translate worst and skim worst.
7. **No hedging without a size.** Not "it seems likely" — instead name the uncertainty: "we measured
   this once, with a test prompt, not a real prompt".
8. **Never open a paragraph with a bare pronoun** referring to the previous paragraph. Readers land
   mid-page. Name the subject again.
9. **Front-load the sentence.** Subject and verb in the first six words. Put conditions after the
   main clause: "Use TCC mode if the server runs as a Windows service" — not "If the server runs as
   a Windows service, then in that case TCC mode should be used."
10. **Lists for lists.** If a sentence contains three or more parallel items, make it a bulleted list
    or a table. Prose is for judgement, not enumeration.
11. **Bold the answer, not the emphasis.** Bold carries the sentence a skimming reader must not miss.
    If half a paragraph is bold, none of it is.
12. **Define on first use, inline, and again in §2.** The reader will not follow a link mid-document.

## The rewrite table

| Instead of                                                | Write                                                     |
| --------------------------------------------------------- | --------------------------------------------------------- |
| utilize, leverage                                         | use                                                       |
| initiate, commence                                        | start                                                     |
| terminate                                                 | stop                                                      |
| in order to                                               | to                                                        |
| due to the fact that                                      | because                                                   |
| at this point in time                                     | now                                                       |
| a number of, several                                      | the number (or "about 12")                                |
| significantly faster                                      | 1.9 times faster                                          |
| performance degradation was observed                      | it became slower — by X                                   |
| there is a possibility that                               | X may happen if Y                                         |
| it should be noted that                                   | *(delete; state the thing)*                               |
| we were unable to determine                               | we did not measure this. To measure it: \<method\>        |
| the aforementioned approach                               | *(name it)*                                               |
| this is non-trivial                                       | this takes \<time\> and needs \<thing\>                   |
| best-in-class, industry-standard, robust                  | *(delete; give the number or the source)*                 |
| optimize, improve                                         | make faster / make smaller / reduce cost — say which      |
| The result was withdrawn.                                 | We withdrew the result.                                   |

## Building the vocabulary table (§2)

Include a term when **any** of these is true:

- It is an acronym (`TCC`, `MoE`, `GGUF`, `SLA`).
- Two readers in the thread have used it to mean different things. These are the highest-value rows.
- It has a common meaning and a narrow meaning here ("program", "engine", "wrapper", "load").
- Your argument turns on the distinction between it and a neighbouring term.

Format — one meaning, in plain words, using only terms already defined:

```markdown
| Word            | Meaning                                                                       |
| --------------- | ----------------------------------------------------------------------------- |
| **Token**       | A piece of a word. About 4 characters of English. A model reads and writes tokens. |
| **Engine**      | The software that does the mathematics on the GPU.                            |
| **Wrapper**     | A program that contains an engine, but does not replace it.                   |
```

Eight to twelve rows is typical. Above about fifteen, the table stops being read — move the rare
terms to inline definitions at first use.

Open the section with the instruction, not just the table: *"Use these words with one meaning only."*

## Numbers

Every number in the document carries three things, either inline or in the table it sits in:

- **The unit.** "659 tokens per second", not "659".
- **The basis.** Measured or calculated? From what sample? On what date? "measured from `gpt-4o`",
  "223 samples", "measured 2026-08-07".
- **Its precision.** Write "about 125" when the run-to-run spread is ±10. False precision ("125.4")
  invites a challenge you cannot defend, and burns the credibility of the numbers that *are* exact.

Ratios beat percentages when the gap is large: "about 5 times too slow" lands harder and is
remembered better than "80% below target". Percentages are right for small differences: "0.3%
slower".

State the direction: "10.3% slower" not "10.3% difference".

## Words to delete on sight

`basically`, `essentially`, `simply`, `just`, `obviously`, `of course`, `clearly`, `actually`,
`very`, `quite`, `fairly`, `really`, `arguably`, `interestingly`, `unfortunately`, `it turns out
that`, `as we all know`.

Each one either adds nothing or, worse, tells the reader their question was stupid. "Simply run the
benchmark" is a sentence that makes a reader who then fails feel foolish, and they will not tell you.

## The mechanical pass

Work through the draft once per rule. Batching is faster and catches more than reading for "style".

1. **Sentence length.** Find every sentence over 25 words. Split or cut it.
2. **Passive voice.** Search `was `, `were `, `been `, `is being`. Rewrite with the actor named,
   or confirm the actor genuinely does not matter.
3. **Synonyms for defined terms.** For each row of §2, search the document for its synonyms and
   replace them.
4. **Bare numbers.** Search for digits. Every hit needs a unit and a basis.
5. **Filler.** Search the delete-on-sight list.
6. **Paragraph openings.** Scan the first three words of each paragraph for `This`, `It`, `They`,
   `That`.
7. **Read the five-line summary cold**, as though you had read nothing else.
