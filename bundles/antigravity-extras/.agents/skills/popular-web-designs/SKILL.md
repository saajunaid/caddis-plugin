---
name: popular-web-designs
description: 54 real-world design systems (Stripe, Linear, Vercel, Supabase, Apple, Notion, Cursor, etc.) as ready-to-use HTML/CSS reference. Exact color palettes, typography hierarchies, component specs, spacing, shadow systems, and font substitutions. Use when building UI that should match a specific company's aesthetic.
source: NousResearch/hermes-agent
---

# Popular Web Designs

54 real-world design systems captured as HTML/CSS references. Each entry maps to a company's complete visual language — colors, typography, components, spacing, shadows, and responsive rules.

## How to Use

1. **Identify the target brand** from the catalog below or from the user's description
2. **Load the detailed template** by reading `templates/<brand>.md` in this skill directory
3. **Extract design tokens** and apply to your HTML
4. **Use the Agent Prompt Guide** in each template for exact CSS values

## Font Substitution (Proprietary → Google Fonts CDN)

| Proprietary Font | CDN Substitute |
|------------------|----------------|
| sohne-var (Stripe) | Source Sans 3 |
| Geist Sans (Vercel) | Geist (on Google Fonts) |
| Inter Variable (Linear) | Inter |
| Berkeley Mono (Linear code) | JetBrains Mono |
| SF Pro Display (Apple) | Inter |
| Circular (Spotify, Airbnb) | DM Sans |
| Söhne (Notion) | Inter |

## Design Selection Guide

**Dark UI / dashboards**: Linear, Cursor, ElevenLabs, Warp, xAI, Ollama  
**Marketing / landing pages**: Stripe, Framer, Apple, SpaceX  
**Developer tools**: Vercel, Supabase, Raycast, Sentry, PostHog  
**Content-first / docs**: Mintlify, Notion, Sanity, MongoDB  
**Terminal / minimal**: Ollama, xAI, VoltAgent, Resend  
**Fintech / trust**: Stripe, Revolut, Wise, Coinbase  
**Enterprise / corporate**: IBM, Intercom, Zapier, Airtable  

## Brand Catalog

> Full detailed templates (color systems, typography tables, component specs, agent prompts) are in `templates/`. Quick reference below.

### AI & Machine Learning

| Brand | Aesthetic | Primary Color | Font |
|-------|-----------|---------------|------|
| Claude | Warm cream, editorial | `#D97706` amber | Georgia + Inter |
| Cohere | Navy + coral | `#FF6B6B` | Inter |
| ElevenLabs | Near-black + purple | `#7C3AED` | Inter |
| Minimax | Dark + blue | `#3B82F6` | Inter |
| Mistral AI | Dark navy + gradient | `#FF7849` orange | Inter |
| Ollama | Terminal black | `#22C55E` green | JetBrains Mono |
| OpenCode AI | Terminal dark | `#4ADE80` | JetBrains Mono |
| Replicate | Pure black minimal | `#FFFFFF` | Geist |
| RunwayML | Black + green accent | `#00E599` | Inter |
| Together AI | Dark + blue | `#3B82F6` | Inter |
| VoltAgent | Dark + teal | `#14B8A6` | JetBrains Mono |
| xAI (Grok) | Pure black + white | `#FFFFFF` | JetBrains Mono |

### Developer Tools & Platforms

| Brand | Aesthetic | Primary Color | Font |
|-------|-----------|---------------|------|
| Cursor | VSCode dark + blue | `#3B82F6` | Inter |
| Expo | Black + blue | `#4630EB` | Inter |
| Linear | Near-black + indigo | `#5E6AD2` | Inter Variable |
| Lovable | White + purple gradient | `#7C3AED` | Inter |
| Mintlify | White + purple | `#7C3AED` | Inter |
| PostHog | Dark + yellow-orange | `#F97316` | Inter |
| Raycast | Dark + orange | `#FF6363` | Inter |
| Resend | Pure black minimal | `#FFFFFF` | Geist |
| Sentry | Dark + green | `#362D59` + `#F55459` | Rubik |
| Supabase | Dark + emerald | `#3ECF8E` | Inter |
| Superhuman | White + dark navy | `#1D1D1D` | -apple-system |
| Vercel | White+black, no-color | `#171717` | Geist |
| Warp | Dark + gradient | `#5B53FF` | Inter |
| Zapier | White + orange | `#FF4A00` | Inter |

### Infrastructure & Cloud

| Brand | Aesthetic | Primary Color | Font |
|-------|-----------|---------------|------|
| ClickHouse | Dark + yellow | `#FAFF69` | Inter |
| Composio | Dark + purple | `#7C3AED` | Inter |
| HashiCorp | Dark + purple | `#844FBA` | Inter |
| MongoDB | White + green | `#00ED64` | Euclid |
| Sanity | White + red | `#F03E2F` | Inter |
| Stripe | White + purple | `#533AFD` | sohne-var→Source Sans 3 |

### Design & Productivity

| Brand | Aesthetic | Primary Color | Font |
|-------|-----------|---------------|------|
| Airtable | White + blue | `#2D7FF9` | Inter |
| Cal.com | White + black minimal | `#111827` | Cal Sans |
| Clay | Dark + gradient | `#6366F1` | Inter |
| Figma | White + purple gradient | `#7C3AED` | Inter |
| Framer | Dark + gradient | `#0A0A0A` | Inter |
| Intercom | Navy + white | `#1F8EFA` | Inter |
| Miro | Yellow + white | `#FFD02F` | Inter |
| Notion | White + minimal | `#37352F` | ui-sans-serif |
| Pinterest | White + red | `#E60023` | Helvetica Neue |
| Webflow | Dark + blue | `#4353FF` | Inter |

### Fintech & Crypto

| Brand | Aesthetic | Primary Color | Font |
|-------|-----------|---------------|------|
| Coinbase | White + blue | `#0052FF` | Coinbase Display |
| Kraken | Dark + purple | `#5741D9` | Inter |
| Revolut | White + dark navy | `#191C1F` | Inter |
| Wise | White + teal-green | `#163300` + `#9FE870` | Inter |

### Enterprise & Consumer

| Brand | Aesthetic | Primary Color | Font |
|-------|-----------|---------------|------|
| Airbnb | White + red-coral | `#FF5A5F` | Cereal→DM Sans |
| Apple | White + black minimal | `#0071E3` | SF Pro→Inter |
| BMW | Dark + blue-silver | `#1C69D4` | BMWTypeNext |
| IBM | White + blue | `#0F62FE` | IBM Plex |
| NVIDIA | Black + green | `#76B900` | NVIDIA Sans |
| SpaceX | Black + minimal | `#FFFFFF` | Inter |
| Spotify | Black + green | `#1DB954` | Circular→DM Sans |
| Uber | Black minimal | `#000000` | Uber Move→Inter |

## Detailed Templates Available

Full design specifications (color system, typography table, component specs, responsive rules, agent prompt guide) available for:
- `templates/linear.app.md` — Linear (complete)
- `templates/stripe.md` — Stripe (complete)
- `templates/vercel.md` — Vercel (complete)

Additional templates can be added to `templates/` as needed. When a template doesn't exist, use the quick reference row above combined with knowledge of the brand's established design language.

## Recommended Pairings

- Pair with **`sketch`** for exploring which brand reference fits the brief
- Pair with **`design-md`** when deliverable is a formal spec file
- Pair with **`warm-editorial-ui`** for your organization's internal app family (already has a complete custom system)
- Pair with **`claude-design`** principles (anti-slop quality standards) when building any HTML artifact
