---
description: Design-first UI brief — lock the aesthetic before writing any code
argument-hint: <what you're building, e.g. "dashboard for NPS scores" or "login page">
---

# /ui-brief — design first, code second

You are about to build a React frontend. **Do not write any code yet.**

Your job right now is to propose the visual direction and get approval before touching a file.

## What you're building

**$ARGUMENTS**

## Step 1 — Load the right skill

**Your organization's internal app family** (an existing internal tool/dashboard suite that shares a
house design system): load `warm-editorial-ui`.

**Matching a known brand** (Stripe, Linear, Vercel, Supabase, Notion, Apple, Cursor, PostHog, or any company the user names): load `popular-web-designs` and read the matching template. Use that brand's exact tokens as the basis for your brief proposal.

**Data dashboard** (not part of an existing internal design system): load `enterprise-dashboard-aesthetic-system`.

**Standalone or public-facing product** (no brand specified): load `frontend-design`.

## Step 2 — Propose the brief (3 things only)

Present exactly this, in plain language, no code:

```
FONT PAIRING
  Heading: <specific font name and weight — not Inter, not Roboto>
  Body:    <specific font name>
  Why:     <one sentence on the mood it creates>

COLOUR STORY
  Background: <hex>  Surface: <hex>  Primary: <hex>  Accent: <hex>
  Why:        <one sentence — warm/cold/bold/editorial?>

ONE ANIMATION MOMENT
  What moves:  <the one element that gets the hero animation>
  How:         <spring entrance / stagger reveal / scroll trigger / etc.>
  Why:         <what it communicates — speed, weight, personality>

LAYOUT APPROACH
  <2 sentences: grid structure, whitespace philosophy, any asymmetry or grid-breaking>
```

If you loaded `popular-web-designs` for a specific brand, use that brand's actual colors and fonts in the brief — not approximations.

## Step 3 — Wait

Do not proceed until the user responds with one of:
- **"go"** — build exactly as proposed
- feedback / changes — revise the brief and re-present, then wait again
- **"skip"** — proceed with your best judgement immediately

## Step 4 — Build

Once approved: implement using the loaded skill as your design system.
Use Framer Motion for the approved animation moment.
Every component must reflect the agreed colour story and font pairing — no fallback to defaults.

### Quality Standards (enforce these during build)

**Avoid AI design slop:**
- No aggressive gradients unless specifically in the brief
- No glassmorphism by default — only if it fits the brand
- No generic SaaS card grids as the default layout
- No fake dashboards with placeholder charts and made-up metrics
- No filler text ("Lorem ipsum", "User Name", "Description here")
- No decorative emojis in headings or UI chrome

**Motion discipline:**
- Use animation as communication, not decoration
- Always respect `prefers-reduced-motion` media query
- One hero animation moment — not every element animating on load
- 44px minimum touch targets on mobile

**Verification:**
- Confirm the file exists before reporting done
- Check browser console for errors if possible
- Never claim to have verified something you did not verify
