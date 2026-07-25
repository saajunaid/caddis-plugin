---
name: humanizer
description: Identify and remove AI writing patterns from text to make it sound natural and human. Covers 29 documented LLM output patterns. Use when asked to humanize, de-AI, un-ChatGPT, or rewrite drafts (blogs, docs, emails, PRs, releases) to sound authentic.
source: NousResearch/hermes-agent
license: MIT
---

# Humanizer

Remove AI-generated writing patterns and restore authentic voice. Based on Wikipedia's "Signs of AI writing" guide and Siqi Chen's original [blader/humanizer](https://github.com/blader/humanizer) (MIT).

**Core insight**: LLMs guess statistically likely continuations. The result trends toward the most probable phrasing — which is how telltale patterns get baked in. Removing them is necessary but not sufficient. The output also needs personality.

## When to Load

- "Humanize this", "de-AI this", "un-ChatGPT this"
- "Rewrite this to sound more natural"
- "This sounds like it was written by AI"
- Before publishing: blog posts, release notes, docs, emails, social posts
- Applying to Claude's own output in a conversation

## Input Methods

1. **Inline** — user pastes text; rewrite in place
2. **File** — `read_file` to load, `write_file` or `patch` to apply
3. **Voice calibration** — user provides a writing sample to match their tone

## The 29 AI Patterns

### Content Patterns (1–6)

**1. Undue significance/legacy emphasis**
Watch for: "stands as," "testament to," "pivotal moment," "broader trends"
Fix: Replace with the specific fact, not the editorial wrapper

**2. Undue notability/media emphasis**
Watch for: "cited by," "leading expert," "active on social media"
Fix: Either state the credential specifically or cut it

**3. Superficial analysis with -ing endings**
Watch for: "highlighting," "underscoring," "reflecting," "symbolizing," "demonstrating"
Fix: Rewrite as a direct statement of what the fact means

**4. Promotional / ad-copy language**
Watch for: "nestled," "vibrant," "breathtaking," "stunning," "renowned," "world-class"
Fix: Describe the actual attribute instead of the adjective

**5. Vague attributions / weasel words**
Watch for: "experts argue," "industry reports suggest," "observers cite"
Fix: Name the source or cut the attribution entirely

**6. Formulaic "Challenges and Future Prospects" sections**
Watch for: Sections that end with "Despite challenges..." followed by optimistic filler
Fix: Either include specific named challenges or remove the section

### Language & Grammar Patterns (7–13)

**7. Overused AI vocabulary**
Post-2023 words that appear far more in AI text than human text:
`actually`, `crucial`, `delve`, `landscape`, `tapestry`, `underscore`, `interplay`, `intricacies`, `groundbreaking`, `revolutionary`, `unleash`, `game-changing`, `seamlessly`, `robust`
Fix: Replace with plain language or cut

**8. Copula avoidance** (replacing "is" with indirect constructions)
Watch for: "serves as," "marks," "boasts," "features," "represents"
Fix: Use "is" or rewrite directly — "X serves as a hub" → "X is a hub"

**9. Negative parallelisms / tailing negations**
Watch for: "not only...but," sentence-ending fragments like "no guessing required"
Fix: Write complete parallel clauses

**10. Rule-of-three overuse**
Watch for: Every point being grouped into exactly three items
Fix: Use the number the content actually requires

**11. Elegant variation** (synonym substitution to avoid repetition)
Watch for: The same concept referred to by a different word every sentence
Fix: Repeat the word if that's what you mean — humans do this

**12. False ranges**
Watch for: "From A to B" where A and B aren't on a meaningful spectrum
Fix: Drop the range framing; state the things directly

**13. Passive voice / subjectless fragments**
Watch for: "It was determined that," "Steps were taken to"
Fix: Name the actor — "We determined," "The team took steps"

### Style Patterns (14–19)

**14. Em dash overuse**
LLMs use "—" far more than humans. Replace with commas, periods, colons, or parentheses in most cases.

**15. Overuse of boldface**
Mechanical emphasis bolding every third concept. Remove unless the bold is doing real work.

**16. Inline-header vertical lists**
Pattern: **Bold phrase**: followed by description, repeated. Fix: Rewrite as flowing prose unless it's genuinely tabular.

**17. Title Case Headings**
Only capitalize the first word and proper nouns. Not Every Main Word.

**18. Decorative emojis**
Remove emojis from headings, bullet points, and lists unless the context requires them (Slack messages, social posts).

**19. Curly quotation marks**
Use straight quotes ("...") not curly ("...") in code contexts.

### Communication Patterns (20–22)

**20. Collaborative chatbot artifacts**
Remove: "I hope this helps!", "Let me know if you need anything!", "Certainly!", "Of course!", "Great question!"

**21. Knowledge-cutoff disclaimers**
Strip: "as of my last update," "based on available information," "while I cannot verify"

**22. Sycophantic / servile tone**
Remove excessive positivity, hedging-to-please, and "let me know what you think" endings

### Filler & Hedging (23–29)

**23. Filler phrases**
| Replace | With |
|---------|------|
| "in order to" | "to" |
| "due to the fact that" | "because" |
| "at this point in time" | "now" |
| "it is important to note that" | just state the fact |
| "please note that" | just state the fact |

**24. Excessive hedging**
"could potentially possibly be argued to suggest" → "may suggest" or just "suggests"

**25. Generic positive conclusions**
"the future looks bright" / "exciting times ahead" → state a specific fact or expectation, or cut entirely

**26. Hyphenated word-pair overuse**
`cross-functional`, `data-driven`, `client-facing`, `best-in-class` — vary usage or replace with plain language

**27. Persuasive authority tropes**
Remove: "at its core," "the real question is," "what really matters here," "the key insight is"

**28. Signposting / meta-announcements**
Cut: "let's dive in," "here's what you need to know," "without further ado," "in this article, we will"

**29. Fragmented headers**
Headers that just restate the section name as a sentence, contributing no information. Remove or make specific.

## Adding Soul (Required — Not Optional)

Removing AI patterns alone leaves soulless prose. Signs your rewrite is still lifeless:
- Uniform sentence length throughout
- No opinions, only neutral reporting
- No acknowledgment of uncertainty or complexity
- Missing first-person perspective where appropriate
- No humor, specificity, or texture

**How to add voice:**
- Have opinions — react to facts, don't just present them
- Vary rhythm — alternate short punchy sentences with longer ones
- Acknowledge complexity — "this is messier than it sounds"
- Use "I" where honest
- Allow specific details — exact numbers, real names, concrete comparisons
- Let tangents exist — a brief aside feels human

## Voice Calibration (Optional)

If the user provides a writing sample:
1. Analyze: sentence length patterns, word choice register, paragraph starters, punctuation habits, recurring phrases
2. Mirror those patterns in the rewrite
3. Don't just remove AI patterns — replace them with patterns from the sample

## Process

1. Read input (use `read_file` if a file path is given)
2. Identify all pattern instances (annotate mentally)
3. Rewrite problematic sections
4. Inject voice — opinions, rhythm variation, specificity
5. Present draft rewrite
6. Self-audit: "What still sounds AI-generated?" (brief bullets)
7. Address remaining tells
8. Present final version
9. For file edits: apply with `patch` (targeted) or `write_file` (full)

## Output Format

```
DRAFT REWRITE
[rewritten text]

REMAINING TELLS
- [bullet: what still sounds AI-generated and why]

FINAL REWRITE
[final version addressing the tells]
```
