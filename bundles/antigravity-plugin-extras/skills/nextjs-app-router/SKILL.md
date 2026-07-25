---
name: nextjs-app-router
description: Next.js 13+ App Router conventions, Server vs Client Components, Server Actions, Middleware, data fetching, Metadata API, and route handlers. Use for Next.js App Router directory structure, Server Actions, SSR/RSC patterns, generateMetadata, layout/page/error/loading.tsx conventions, route groups, parallel routes, or hydration issues. Companion to react-dev and react-best-practices.
---

# Next.js App Router Skill

Covers Next.js 13+ App Router conventions. Companion to `react-dev` (typing) and `react-best-practices` (patterns). Always read those for React-level decisions.

## 1. File Conventions

```
app/
├── layout.tsx          # Root shell — fonts, providers, global nav. Always present.
├── page.tsx            # Default route segment UI
├── loading.tsx         # Suspense boundary UI while segment loads
├── error.tsx           # Error boundary ('use client' required)
├── not-found.tsx       # 404 for segment
├── template.tsx        # Re-mounts on navigation (vs layout which persists)
├── (marketing)/        # Route group — no URL segment, just org
│   ├── about/page.tsx
│   └── pricing/page.tsx
├── dashboard/
│   ├── layout.tsx      # Nested layout (persists across dashboard routes)
│   └── settings/page.tsx
└── api/
    └── webhook/route.ts  # Route handler
```

### Key Rules
- `error.tsx` **must** be `'use client'` — React error boundaries require it.
- `loading.tsx` wraps the segment's `page.tsx` in `<Suspense>` automatically.
- `template.tsx` re-mounts children on every navigation; use only when fresh mount is needed.
- Route groups `(group)` do not affect URL paths — use for layout isolation or code organisation.

## 2. Server vs Client Components — Decision Tree

```
Does this component need:
  - useState / useReducer?           → 'use client'
  - useEffect?                       → 'use client'
  - Browser APIs (window, document)? → 'use client'
  - Event listeners?                 → 'use client'
  - Framer Motion / animation libs?  → 'use client'
  - Third-party client-side context? → 'use client'
  Otherwise:                         → Server Component (default)
```

### Composition Pattern
```tsx
// ✅ GOOD: Push 'use client' to the leaf
// app/dashboard/page.tsx — Server Component
import { InteractiveChart } from './interactive-chart'

export default async function DashboardPage() {
  const data = await fetchData()  // Direct async/await — no useEffect needed
  return <InteractiveChart initialData={data} />
}

// interactive-chart.tsx
'use client'
export function InteractiveChart({ initialData }: { initialData: Data }) {
  const [filter, setFilter] = useState('all')
  // ...
}
```

```tsx
// ❌ BAD: Marking the whole page client just for one button
'use client'
export default async function Page() {  // 'async' is invalid in client components
  const data = await fetchData()  // This won't work in client components
}
```

## 3. Server Actions

Server Actions are async functions that run on the server, callable from Client Components.

```tsx
// app/actions/user.ts
'use server'

import { revalidatePath, revalidateTag } from 'next/cache'

export async function updateUser(userId: string, formData: FormData) {
  const name = formData.get('name') as string
  await db.user.update({ where: { id: userId }, data: { name } })
  revalidatePath('/dashboard/profile')  // Revalidate specific path
}

export async function deletePost(postId: string) {
  await db.post.delete({ where: { id: postId } })
  revalidateTag('posts')  // Revalidate by cache tag
}
```

### `useActionState` (React 19 / Next.js 14+)
```tsx
'use client'
import { useActionState } from 'react'
import { updateUser } from '@/app/actions/user'

type State = { error?: string; success?: boolean }

export function ProfileForm({ userId }: { userId: string }) {
  const [state, action, isPending] = useActionState<State, FormData>(
    async (_, formData) => {
      try {
        await updateUser(userId, formData)
        return { success: true }
      } catch {
        return { error: 'Update failed' }
      }
    },
    {}
  )

  return (
    <form action={action}>
      <input name="name" disabled={isPending} />
      {state.error && <p role="alert">{state.error}</p>}
      <button type="submit" disabled={isPending}>{isPending ? 'Saving…' : 'Save'}</button>
    </form>
  )
}
```

## 4. Middleware

```ts
// middleware.ts (at project root, NOT in app/)
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Auth guard
  const token = request.cookies.get('auth-token')?.value
  if (pathname.startsWith('/dashboard') && !token) {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  // A/B test header
  const response = NextResponse.next()
  response.headers.set('x-variant', 'control')
  return response
}

export const config = {
  matcher: ['/dashboard/:path*', '/api/:path*'],
  // Use edge runtime for simple string ops — avoids cold start
}
```

## 5. Data Fetching

### Server Component Fetch with Caching
```tsx
// Cached fetch: deduplicated across the request lifecycle
async function getUser(id: string) {
  const res = await fetch(`https://api.example.com/users/${id}`, {
    next: { revalidate: 3600 },  // ISR: revalidate every hour
    // next: { tags: ['user'] },  // Tag-based revalidation
    // cache: 'no-store',         // Dynamic — no cache
  })
  if (!res.ok) throw new Error('Failed to fetch')
  return res.json()
}
```

### Parallel Data Fetching
```tsx
// ✅ GOOD: Parallel — not waterfall
export default async function Page({ params }: { params: { id: string } }) {
  const [user, posts, analytics] = await Promise.all([
    getUser(params.id),
    getPosts(params.id),
    getAnalytics(params.id),
  ])
  return <Dashboard user={user} posts={posts} analytics={analytics} />
}
```

### Suspense Streaming
```tsx
import { Suspense } from 'react'

export default function Page() {
  return (
    <>
      <Header />
      <Suspense fallback={<Skeleton />}>
        <AsyncDataTable />  {/* Streams in when ready */}
      </Suspense>
      <Suspense fallback={<ChartSkeleton />}>
        <AsyncChart />
      </Suspense>
    </>
  )
}
```

## 6. Metadata API

```tsx
// Static metadata
export const metadata = {
  title: 'Dashboard',
  description: 'Your personalised dashboard',
}

// Dynamic metadata
export async function generateMetadata({ params }: { params: { slug: string } }) {
  const post = await getPost(params.slug)
  return {
    title: post.title,
    description: post.excerpt,
    openGraph: {
      title: post.title,
      images: [{ url: post.coverImage, width: 1200, height: 630 }],
    },
    twitter: { card: 'summary_large_image', title: post.title },
  }
}
```

## 7. Route Handlers

```ts
// app/api/users/route.ts
import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const page = Number(searchParams.get('page') ?? '1')
  const users = await db.user.findMany({ skip: (page - 1) * 20, take: 20 })
  return NextResponse.json({ users, page })
}

export async function POST(request: NextRequest) {
  const body = await request.json()
  // Validate with zod before DB write
  const parsed = CreateUserSchema.safeParse(body)
  if (!parsed.success) return NextResponse.json({ error: parsed.error.flatten() }, { status: 422 })
  const user = await db.user.create({ data: parsed.data })
  return NextResponse.json(user, { status: 201 })
}
```

## 8. Common Pitfalls

| Pitfall | Cause | Fix |
|---------|-------|-----|
| Hydration mismatch | Server HTML ≠ client render (dates, random IDs, browser-only APIs) | Wrap in `<ClientOnly>` component or use `useEffect` for client-only values |
| `'use client'` creep | Adding hooks to parent forces entire tree client | Push boundary to leaf — pass serialisable data as props |
| Nested layout confusion | Inner `layout.tsx` doesn't wrap sibling `page.tsx` at same level | Layouts only wrap children segments, not siblings |
| Stale cache | `fetch` cached too aggressively | Use `revalidateTag` on mutation, or `cache: 'no-store'` for real-time data |
| Server Action in Server Component | Calling a Server Action from a Server Component via form is fine; importing into client requires `'use server'` import | Declare `'use server'` at top of action file, not per-function |
| Missing error handling in route handler | Unhandled error returns 500 with Next.js HTML error page | Always return `NextResponse.json({ error: ... }, { status })` |

## 9. Quick Reference Checklist

- [ ] `error.tsx` has `'use client'` directive
- [ ] No `async`/`await` inside Client Components — lift to Server Component or Server Action
- [ ] Parallel fetches use `Promise.all`, not sequential `await`
- [ ] `revalidatePath` or `revalidateTag` called after every mutating Server Action
- [ ] Middleware `matcher` is as specific as possible — avoid `'/'` matching everything
- [ ] `generateMetadata` defined for every public-facing page
- [ ] Route handlers validate input with zod before touching the database
