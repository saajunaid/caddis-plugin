---
name: api-client-patterns
description: Typed API client patterns for consuming REST APIs and tRPC. Use for typed fetch wrappers, zod response validation, API client factory, auth injection, TanStack Query (useQuery, useMutation, infinite queries, optimistic updates), tRPC end-to-end types, error handling with discriminated unions, OpenAPI client codegen, or pagination envelopes. Complements backend-development (server side) with client-side consumption patterns.
---

# API Client Patterns Skill

Typed, maintainable API clients — from simple fetch wrappers to full TanStack Query integration and tRPC.

## 1. Typed Fetch Wrapper with Zod Validation

```ts
// lib/api/fetcher.ts
import { z } from 'zod'

export type ApiError = { type: 'network'; message: string }
                     | { type: 'validation'; issues: z.ZodIssue[] }
                     | { type: 'http'; status: number; body: unknown }

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError }

async function fetchJson<T>(
  url: string,
  schema: z.ZodSchema<T>,
  init?: RequestInit,
): Promise<ApiResult<T>> {
  let response: Response

  try {
    response = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  } catch (e) {
    return { ok: false, error: { type: 'network', message: String(e) } }
  }

  if (!response.ok) {
    return { ok: false, error: { type: 'http', status: response.status, body: await response.json().catch(() => null) } }
  }

  const raw = await response.json()
  const parsed = schema.safeParse(raw)

  if (!parsed.success) {
    return { ok: false, error: { type: 'validation', issues: parsed.error.issues } }
  }

  return { ok: true, data: parsed.data }
}
```

## 2. API Client Factory Pattern

```ts
// lib/api/client.ts
import { z } from 'zod'

function createApiClient(baseUrl: string, getAuth: () => string | null) {
  async function request<T>(
    method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
    path: string,
    schema: z.ZodSchema<T>,
    body?: unknown,
  ) {
    const token = getAuth()
    return fetchJson(`${baseUrl}${path}`, schema, {
      method,
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  }

  return {
    get: <T>(path: string, schema: z.ZodSchema<T>) => request('GET', path, schema),
    post: <T>(path: string, schema: z.ZodSchema<T>, body: unknown) => request('POST', path, schema, body),
    put: <T>(path: string, schema: z.ZodSchema<T>, body: unknown) => request('PUT', path, schema, body),
    patch: <T>(path: string, schema: z.ZodSchema<T>, body: unknown) => request('PATCH', path, schema, body),
    delete: <T>(path: string, schema: z.ZodSchema<T>) => request('DELETE', path, schema),
  }
}

// Usage
import { getAccessToken } from '@/lib/auth'
export const api = createApiClient(process.env.NEXT_PUBLIC_API_URL!, getAccessToken)
```

## 3. Response Contracts — Pagination and Error Envelopes

```ts
// lib/api/schemas.ts — reusable response shapes
import { z } from 'zod'

export const paginatedSchema = <T extends z.ZodTypeAny>(itemSchema: T) =>
  z.object({
    data: z.array(itemSchema),
    total: z.number(),
    page: z.number(),
    per_page: z.number(),
    has_next: z.boolean(),
  })

export const apiErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.string()).optional(),
})

// Domain schemas
export const userSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  email: z.string().email(),
  role: z.enum(['admin', 'user', 'viewer']),
  createdAt: z.coerce.date(),
})

export type User = z.infer<typeof userSchema>
export const paginatedUsersSchema = paginatedSchema(userSchema)
```

## 4. TanStack Query Integration

### Setup (`QueryClientProvider`)
```tsx
// app/providers.tsx
'use client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { useState } from 'react'

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { staleTime: 60_000, retry: 1 },
    },
  }))

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  )
}
```

### `useQuery` — Fetching
```tsx
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api/client'
import { paginatedUsersSchema } from '@/lib/api/schemas'

// Query key factory — centralized, type-safe
export const userKeys = {
  all: ['users'] as const,
  lists: () => [...userKeys.all, 'list'] as const,
  list: (filters: UserFilters) => [...userKeys.lists(), filters] as const,
  detail: (id: string) => [...userKeys.all, 'detail', id] as const,
}

export function useUsers(filters: UserFilters) {
  return useQuery({
    queryKey: userKeys.list(filters),
    queryFn: async () => {
      const params = new URLSearchParams(filters as Record<string, string>)
      const result = await api.get(`/users?${params}`, paginatedUsersSchema)
      if (!result.ok) throw new Error(result.error.message ?? 'Failed to fetch users')
      return result.data
    },
  })
}
```

### `useMutation` — Creating/Updating
```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

export function useCreateUser() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (body: CreateUserInput) => {
      const result = await api.post('/users', userSchema, body)
      if (!result.ok) throw new Error('Failed to create user')
      return result.data
    },
    onSuccess: () => {
      // Invalidate all user list queries
      queryClient.invalidateQueries({ queryKey: userKeys.lists() })
      toast.success('User created successfully')
    },
    onError: (error) => {
      toast.error(error.message)
    },
  })
}
```

### Optimistic Updates
```tsx
export function useUpdateUser(id: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (patch: Partial<User>) => api.patch(`/users/${id}`, userSchema, patch),

    onMutate: async (patch) => {
      await queryClient.cancelQueries({ queryKey: userKeys.detail(id) })
      const previous = queryClient.getQueryData(userKeys.detail(id))
      queryClient.setQueryData(userKeys.detail(id), (old: User) => ({ ...old, ...patch }))
      return { previous }  // Return context for rollback
    },

    onError: (_err, _vars, context) => {
      // Rollback to previous value
      queryClient.setQueryData(userKeys.detail(id), context?.previous)
    },

    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: userKeys.detail(id) })
    },
  })
}
```

### Infinite Queries — Pagination
```tsx
import { useInfiniteQuery } from '@tanstack/react-query'

export function useInfiniteUsers() {
  return useInfiniteQuery({
    queryKey: userKeys.lists(),
    queryFn: ({ pageParam = 1 }) =>
      api.get(`/users?page=${pageParam}&per_page=20`, paginatedUsersSchema)
        .then(r => { if (!r.ok) throw new Error('Fetch failed'); return r.data }),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.has_next ? lastPage.page + 1 : undefined,
  })
}

// Usage
const { data, fetchNextPage, hasNextPage, isFetchingNextPage } = useInfiniteUsers()
const users = data?.pages.flatMap(p => p.data) ?? []
```

## 5. tRPC — End-to-End Type Safety

```ts
// server/router.ts (Next.js App Router example)
import { initTRPC } from '@trpc/server'
import { z } from 'zod'

const t = initTRPC.create()
const router = t.router
const publicProcedure = t.procedure

export const appRouter = router({
  users: router({
    list: publicProcedure
      .input(z.object({ page: z.number().default(1) }))
      .query(({ input }) => getUsersPaginated(input.page)),

    create: publicProcedure
      .input(z.object({ name: z.string(), email: z.string().email() }))
      .mutation(({ input }) => createUser(input)),
  }),
})

export type AppRouter = typeof appRouter
```

```tsx
// Client usage — fully typed, no schemas needed client-side
const { data } = api.users.list.useQuery({ page: 1 })
const createUser = api.users.create.useMutation({
  onSuccess: () => utils.users.list.invalidate(),
})
```

## 6. Error Handling — Discriminated Unions

```tsx
// Typed error display in components
function UserListView() {
  const { data, error, status } = useUsers({})

  if (status === 'pending') return <Skeleton />
  
  if (status === 'error') {
    // error is typed as Error from React Query
    return <ErrorAlert message={error.message} />
  }

  return <UserTable data={data.data} />
}
```

```ts
// Custom error classes for better discrimination
export class ApiValidationError extends Error {
  constructor(public issues: z.ZodIssue[]) {
    super('Validation failed')
    this.name = 'ApiValidationError'
  }
}

export class ApiHttpError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`HTTP ${status}`)
    this.name = 'ApiHttpError'
  }
}
```

## 7. OpenAPI Client Codegen

```bash
# Install openapi-typescript-codegen
pnpm add -D openapi-typescript-codegen

# Generate client from OpenAPI spec
npx openapi-typescript-codegen \
  --input https://api.example.com/openapi.json \
  --output src/lib/api/generated \
  --client axios  # or fetch
```

Or use `@hey-api/openapi-ts` for modern output:
```bash
pnpm add -D @hey-api/openapi-ts
npx @hey-api/openapi-ts -i openapi.json -o src/lib/api/generated -c fetch
```

**When to use codegen**: When an OpenAPI spec exists and is maintained. When building typed wrappers over a third-party API. Wrap generated clients in your factory pattern — don't expose them directly.

## 8. Retry Logic

```ts
async function fetchWithRetry<T>(
  fn: () => Promise<ApiResult<T>>,
  maxRetries = 3,
  backoffMs = 300,
): Promise<ApiResult<T>> {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const result = await fn()
    if (result.ok) return result
    if (result.error.type === 'http' && result.error.status < 500) return result  // Don't retry 4xx
    if (attempt < maxRetries - 1) await new Promise(r => setTimeout(r, backoffMs * 2 ** attempt))
  }
  return fn()
}
```

TanStack Query handles retries with `retry` option — use that for query/mutation retries instead of manual loops.

## 9. Checklist

- [ ] All API responses validated with Zod schemas
- [ ] Typed `ApiResult<T>` discriminated union for every fetch
- [ ] API client factory with auth injection, not per-call token access
- [ ] Query keys use factory pattern (`userKeys.list(filters)`)
- [ ] `useMutation` invalidates related queries `onSuccess`
- [ ] Optimistic updates roll back on error via `onError` context
- [ ] Infinite queries use `getNextPageParam` from server response
- [ ] tRPC used when full-stack TypeScript with no codegen needed
- [ ] Retry limited to 5xx errors, not 4xx
- [ ] Error states displayed to user — not silently swallowed
