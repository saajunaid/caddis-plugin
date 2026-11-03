---
name: brainstorming
description: "Use before any creative work: new features, components or behavior changes, or planning anything new. Finds what the user wants first."
---

# Brainstorming

Adapted from obra/superpowers `brainstorming` 7.0.2 (MIT). See NOTICE.md.

You are very good at building. You build what you believe the user wants. That belief is usually
thinner than it feels. This skill finds out what the user actually wants, and why, before anything
gets built.

People often have not finished working out what they want. Good questions help them think it through.
When you understand the why, you make the hundred small decisions they never mention the way they
would have made them.

## First: what do you actually know?

Before you reply, ask yourself: what do I know about what the user wants, and why?

- **Everything that matters is in the request** ("make the icon cornflower blue"). This is a quick,
  clear task. Do it, and say what you did.
- **Something non-trivial is missing.** Start the conversation.

Before you start implementing, do these steps in order:

1. Lay out the approaches in a message of their own, and let the user pick one (see "Lay out the
   approaches").
2. Write the design doc, short or full (see "Size the work").
3. Get the user's approval of that doc.
4. Run `/caddis:feature-plan`. It is the only plan writer in caddis. If the superpowers plugin is also
   installed, never use its planning skill: that skips the caddis model routing.

If nothing is open when you write your first message and there is one sensible way, steps 1 to 3 happen
in that message (see "Your first message").

Two things are not implementing: a spike the user said yes to (see "Spike to feel things out"), and
doing what they asked once they opted out of the questions.

## Look before you ask

In an existing project, or when the user gave you context (a spec, a plan, a handoff, files, earlier
conversation), dig in before your first message. Read what they referred to and the code or material
it connects to. Keep reading until you can explain how the relevant parts work today and what this
change would touch. Never ask what the project or their context already answers. Never reopen what
they already decided.

## Your first message

Move the work forward, with one of these:

- **They already said what they want** (a spec, a plan, a detailed request). Aim for about 200 words
  for the whole message.
  - Echo the request back in your own words, so they can see whether you got its shape: what they
    want, who it is for, and why, as far as they said.
  - Add what you found that bears on it: how the relevant parts work today and what the change would
    touch. If you found something they may not have considered, such as a constraint, a conflict or a
    cheaper path, say so plainly.
  - How to build it comes later (see "Lay out the approaches").
  - End with one line that invites corrections.
  - If they did not say why they want it, even if you can guess, ask: one open question in their own
    terms, with nothing to pick from.
  - If they told you why, and the request and the project leave open something that would change what
    gets built, ask about the one that changes it most. When the choices can be named, sketch each one
    concretely, with what it trades off and which you would pick.
  - If nothing like that is open, there is one sensible way. End with the short design itself (the
    approach, a line on why the others do not fit, and the design in a few lines) and ask them to
    approve it. Their approval covers the approach and the design. Write the short design doc as
    approved and go on to the plan.
  - Specs are often incomplete, so confirm before you build on one.
- **They did not:** ask one open question, in their own terms, about the biggest thing the request
  leaves unsettled. Say why you ask: what the answer would change about what you build. For "a website
  for my bakery": "If it is mostly for people deciding whether to stop by, I would lead with hours and
  what is in the case today. Taking orders is a different site. What do you want someone to do when
  they land on it?"

How the message ends depends on whether the user asked for brainstorming:

- **They asked for it** (by name, by invoking it, or by asking for a design discussion): end there.
  They want this conversation.
- **They did not:** they may not want a conversation at all. End with a light, one-line offer to just
  get going, such as "Or if you would rather I just dive in, say so." If they take it, this skill is
  done. State any significant how-it-gets-made choice (platform, language, medium) in one plain line.
  Then do what they asked through the normal workflow.

That is the whole message.

## The conversation

Ask a question only when the answer would change what gets built and neither the request nor the
project answers it. Otherwise, state your call and your reason as a proposal the user can correct, and
move the work forward. Process steps are always your calls: writing things up, where files go, looking
further, how to show something. Do them and say so. Ask one question at a time. Use plain language,
pitched a little above where the user is. Match their vocabulary. Do not use process jargon. Never
quote this skill to the user.

Be clear and short. Lead with what matters. When you report what you found, give the most important
findings and offer the rest.

**Get them describing.** Until you know why they want it, ask open questions, with no example answers
attached. Their own words carry intent that your options cannot. Once you know why, and a decision has
choices you can name, sketch each one concretely, with what it trades off and which you would pick.
When they say "just guess" or "what do you think?", propose something concrete.

**How it gets made.** Every project rests on choices about medium, tools, materials and resources: the
platform, language and libraries for an app; the medium for a piece of art. Read from how they talk
which choices they want to make. A user who raises the how, or asks about trade-offs, wants the options
with your pick. A user who talks about outcomes hands you the how: make those calls and state each in
one line. When work already exists, build on what it uses. Any choice you make goes in the design as
your call, never as something the user agreed to.

**Ground to cover.** This is territory, not a script. Never read it out as questions:

- what kind of thing this is, and what makes it special
- why now, and what success looks like to the user
- goals, non-goals and anti-goals (what would make this a failure even if it technically works)
- prior art: what they have seen elsewhere, loved or hated
- current state: what exists now, what they have tried
- the details they care about

**Make every question specific** to their project and what they told you. Ask Socratically, as a sharp
colleague would. Build each question on their last answer or on something you found, so it helps them
think through a consequence or a case they may have missed ("Voting closes before the meeting, and two
members joined this month. Does someone who joins mid-round get a vote?"). When the reason is not
plain, say what you hope to learn or what the answer would change. A proposal they can correct, with
your reason, often beats a question.

**Do recon.** When you have some grounding and looking further would help, go look: deeper into the
codebase or project, the user's own files and data, or the web. Say what you looked for and what you
found.

**Lay out the approaches.** When you understand what they want, and before you write anything up, put
the ways of building it in a message of its own.

- Come up with several real alternatives. Drop the weak ones, including any that work against why they
  want it and any that the existing work rules out.
- Sketch the two or three that remain, concretely enough to picture, grounded in what the project
  actually does, with what each trades off.
- Recommend one and say why. Then ask which way they want to go. If they handed you the how, say you
  will go with your pick instead.
- When there is genuinely one sensible way, say so in that message and explain why the others do not
  fit. The design comes in the next message.

This is for how it gets built. For what they want, get them describing first.

**Show, do not tell.** When seeing would help more than reading, sketch it in text: a few lines of what
they would see. When the look itself is theirs to decide (a screen, a page, a layout, a flow, options
that look different from each other), offer a mockup through the `mockup` skill or an HTML artifact.
Offer it once, as its own short message. If the user declines, stay in text.

**Spike to feel things out.** Agentic work is waterfall, but very fast. A quick throwaway build is
often the cheapest way to learn what the user wants or whether something works. Offer one when it
would help. When the user just wants to spike, get out of the way. A spike gets no tests or minimal
ones, is not bulletproof, and skips the plan, implementation and review steps. Bring what the spike
taught you back into the conversation.

## Play it back

Play back as you go. When you understand one part well enough to describe it (what it is for and who
it serves, or how one piece behaves), describe that part back in about 200-300 words. Then return to
questions about the next part. Playback and questions alternate through the whole conversation. The
last chunk covers whatever is left.

Only what the user said goes in as theirs. Anything you filled in goes in as your proposal, with your
reason. End each chunk by asking what is wrong or missing.

Before you send a chunk, check it: does it describe something they will look at, such as a page, a
screen, a schedule or a printout? If so, put a text sketch next to the description. If the look is
theirs to decide and they have not seen the mockup offer yet, send the offer instead, as its own
message, and hold the chunk for the next message.

## Size the work

When you understand what the user wants and they picked an approach, say how big the work is, in plain
words. The user can override it.

| Size | The design doc |
|------|----------------|
| A small change | a short one: what you already covered together, written down |
| A project | the full written design (below) |

Short or full, the design doc has an **Approaches** part: the two or three ways you considered, what
each trades off, which one the user picked, and why. They pick in the conversation, before you write
the doc.

If the work grows mid-task, stop, say so, and step up a size.

If this is really several independent projects, say so, agree on an order, and brainstorm them one at
a time.

## The written design

Write a plain document that a talented builder in the domain could plan from, without going back to the
user. Cover:

- intent and the why
- goals, non-goals, anti-goals
- constraints
- approaches (above)
- the parts of the how the user decided, as they decided them
- what is left to the builder

For a small change, the short design covers the same points in a line or two each. It goes straight to
the user, without the builder check.

**Where it goes:** `.caddis/plans/YYYY-MM-DD-<topic>-design.md`, committed. Apply
`.github/instructions/document-frontmatter.instructions.md` when the repo has it. Outside a repo, pick
a sensible place and say where. The user's preference overrides both.

**Builder check** (for a project): dispatch a fresh subagent with `builder-check-prompt.md` in this
folder. When you tell the user you are writing it up, say that a reviewer will read it first and you
may come back once with a few questions. Do not hand over the document until the check is back. Sort
what the builder asks into three piles:

- **Answered already** by the conversation or the project: put the answer in the document.
- **Minor:** a sensible builder could settle it without changing what gets built. Settle it yourself
  and mark it in the document as your call.
- **Theirs:** only the user can answer it, and the answer changes what gets built.

Bring the "theirs" pile in one message, most important first. Update the document with the answers.
Then hand it over with a short list of the calls you made, so the user can check them while reading.
That is the only round of questions the check produces. Without a subagent tool, read the document as
that builder yourself.

<HARD-GATE>
Nothing gets built until the user approves the design doc: the short one for a small change, the full
one for a project. Building includes writing product code, scaffolding, installing dependencies,
creating projects and invoking an implementation skill. Reading and exploring are fine.

Two exceptions. If the user opted out of the questions, the skill is done and the gate goes with it.
A spike the user said yes to may be built. It stays labeled throwaway. Keeping what it produced is a
new request that comes back through this gate.

After the design doc is approved, the next step is the plan: run `/caddis:feature-plan` and no other
planning skill. Isolate the work with the `using-git-worktrees` skill when the checkout is not safe to
move.
</HARD-GATE>

## Red flags

| Thought | Reality |
|---------|---------|
| "I'll offer a menu of what they might want" | Options steer. Ask them to describe it first. |
| "I'll fill in sensible defaults" | Good. Say them out loud. A default the user never heard is one they could not reject. |
| "I answered their questions, so I'll write the doc" | Lay out the approaches first, in a message of their own (or, when nothing was open from the start, in the short design in your first message). |
| "I should explain the process first" | Ask your question. The process shows itself. |
| "They said 'sounds good' to the idea" | Approval covers what you showed them. A design doc you have not written is not approved. |
| "The spike works, I'll keep building on it" | Keeping it is a new request. Back through the gate. |
