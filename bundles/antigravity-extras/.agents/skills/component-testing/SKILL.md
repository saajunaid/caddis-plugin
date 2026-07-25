---
name: component-testing
context: fork
description: React component testing with Vitest, Testing Library, MSW, and renderHook. Use for Vitest setup, jsdom/happy-dom config, Testing Library queries, userEvent, component unit tests, testing React hooks, MSW API mocking, snapshot testing, or testing loading/error states. Complements playwright (E2E) and tdd-workflow (methodology).
---

# Component Testing Skill

React component and hook testing with Vitest + Testing Library. For E2E tests, use the `playwright` skill. For methodology, use `tdd-workflow`. This skill covers unit and integration testing of components.

## 1. Vitest Setup

### `vite.config.ts`
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',      // or 'happy-dom' (faster, less spec-compliant)
    globals: true,             // No need to import describe/it/expect
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.stories.*', 'src/test/**'],
      thresholds: { lines: 80, functions: 80, branches: 70 },
    },
  },
})
```

### `src/test/setup.ts`
```ts
import '@testing-library/jest-dom'    // Adds toBeInTheDocument(), toHaveValue(), etc.
import { cleanup } from '@testing-library/react'
import { afterEach, beforeAll, afterAll } from 'vitest'
import { server } from './msw/server'  // MSW server (if using)

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => { cleanup(); server.resetHandlers() })
afterAll(() => server.close())
```

## 2. Testing Library — Query Priority

Use queries from most to least accessible:

| Priority | Query | Why |
|---|---|---|
| 1 | `getByRole` | Tests semantic HTML + ARIA — closest to real user experience |
| 2 | `getByLabelText` | Tests forms with labels — accessibility signal |
| 3 | `getByPlaceholderText` | Acceptable for inputs without labels |
| 4 | `getByText` | Tests text content |
| 5 | `getByDisplayValue` | Tests current input/textarea/select value |
| 6 | `getByAltText` | Tests image alt text |
| 7 | `getByTitle` | Low priority — title attributes are often hidden |
| **Avoid** | `getByTestId` | Last resort only — no accessibility signal |

```tsx
// ✅ GOOD: Role + accessible name
const button = screen.getByRole('button', { name: /save changes/i })

// ✅ GOOD: Label association
const emailInput = screen.getByLabelText(/email/i)

// ❌ AVOID unless no alternative
const element = screen.getByTestId('submit-btn')
```

### Query Variants
- `getBy*` — throws if not found (synchronous)
- `queryBy*` — returns null if not found (for negative assertions)
- `findBy*` — returns Promise, waits for element to appear (async)
- `getAllBy*` / `queryAllBy*` / `findAllBy*` — multiple elements

## 3. `userEvent` vs `fireEvent`

Always prefer `userEvent` — it simulates real browser interactions (focus, pointer, keyboard events in sequence).

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ✅ GOOD: userEvent (realistic user simulation)
test('submits form on Enter key', async () => {
  const user = userEvent.setup()
  render(<SearchForm onSearch={vi.fn()} />)

  await user.type(screen.getByRole('textbox', { name: /search/i }), 'react testing')
  await user.keyboard('{Enter}')

  expect(screen.getByRole('button', { name: /search/i })).toBeDisabled()
})

// ❌ BAD: fireEvent (bypasses realistic event chain)
fireEvent.click(submitButton)  // Skips hover, focus, pointer-down events
```

## 4. Component Test Patterns

### Arrange-Act-Assert (AAA)
```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UserCard } from './UserCard'

describe('UserCard', () => {
  const defaultProps = {
    user: { id: '1', name: 'Alice', email: 'alice@example.com', role: 'admin' },
    onEdit: vi.fn(),
  }

  it('renders user display name', () => {
    // Arrange
    render(<UserCard {...defaultProps} />)

    // Assert
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('alice@example.com')).toBeInTheDocument()
  })

  it('calls onEdit when Edit button clicked', async () => {
    const user = userEvent.setup()
    // Arrange
    render(<UserCard {...defaultProps} />)

    // Act
    await user.click(screen.getByRole('button', { name: /edit/i }))

    // Assert
    expect(defaultProps.onEdit).toHaveBeenCalledWith('1')
    expect(defaultProps.onEdit).toHaveBeenCalledTimes(1)
  })
})
```

### Unit vs Integration
- **Unit**: Single component in isolation, mock all dependencies, fast.
- **Integration**: Multiple components together with real child renders, mock only external APIs.

```tsx
// Unit: mock child
vi.mock('./Avatar', () => ({ Avatar: () => <div data-testid="avatar" /> }))

// Integration: real children, only mock fetch
// MSW handles API responses (see §5)
```

## 5. Testing Hooks — `renderHook`

```tsx
import { renderHook, act } from '@testing-library/react'
import { useCounter } from './useCounter'

describe('useCounter', () => {
  it('increments count', () => {
    const { result } = renderHook(() => useCounter(0))
    
    act(() => result.current.increment())
    
    expect(result.current.count).toBe(1)
  })

  it('respects initial value', () => {
    const { result } = renderHook(() => useCounter(5))
    expect(result.current.count).toBe(5)
  })
})
```

## 6. Async Testing — Loading and Error States

```tsx
import { render, screen, waitFor, waitForElementToBeRemoved } from '@testing-library/react'

it('shows loading skeleton then data', async () => {
  render(<UserList />)

  // Loading state is visible
  expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument()

  // Wait for loading to finish
  await waitForElementToBeRemoved(() => screen.queryByRole('status', { name: /loading/i }))

  // Data is visible
  expect(screen.getByText('Alice')).toBeInTheDocument()
})

it('shows error message on fetch failure', async () => {
  // Override MSW handler for this test
  server.use(
    http.get('/api/users', () => HttpResponse.error())
  )

  render(<UserList />)

  await waitFor(() => {
    expect(screen.getByRole('alert')).toHaveTextContent(/failed to load/i)
  })
})
```

## 7. MSW — API Mocking

```ts
// src/test/msw/handlers.ts
import { http, HttpResponse } from 'msw'

export const handlers = [
  http.get('/api/users', () => {
    return HttpResponse.json([
      { id: '1', name: 'Alice', email: 'alice@example.com' },
      { id: '2', name: 'Bob', email: 'bob@example.com' },
    ])
  }),

  http.post('/api/users', async ({ request }) => {
    const body = await request.json()
    return HttpResponse.json({ id: '3', ...body }, { status: 201 })
  }),
]
```

```ts
// src/test/msw/server.ts
import { setupServer } from 'msw/node'
import { handlers } from './handlers'

export const server = setupServer(...handlers)
```

### Per-test Override
```ts
it('handles 404 gracefully', async () => {
  server.use(
    http.get('/api/users/:id', () => HttpResponse.json({ error: 'Not found' }, { status: 404 }))
  )
  // test body…
})
```

## 8. Snapshot Testing

Use sparingly — prefer explicit assertions. Inline snapshots are better than file snapshots.

```tsx
// ✅ GOOD: Inline snapshot — diff visible in code review
it('renders badge correctly', () => {
  const { container } = render(<Badge variant="success">Active</Badge>)
  expect(container.firstChild).toMatchInlineSnapshot(`
    <span class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-green-100 text-green-800">
      Active
    </span>
  `)
})

// ❌ BAD: File snapshot for large component — diffs are noise
expect(screen.getByRole('dialog')).toMatchSnapshot()
```

## 9. RSC Testing Limitations and Workarounds

React Server Components cannot be rendered in Vitest (no Node.js RSC renderer yet).

| Situation | Solution |
|---|---|
| Server Component under test | Extract logic to a tested pure function; test the function |
| Client Component with RSC parent | Test Client Component in isolation, mock Server Component output |
| Server Action | Test via integration test with MSW or direct function call |
| Page component | E2E test with Playwright |

```tsx
// Extract business logic from RSC
export async function getPageData(id: string): Promise<PageData> {
  return db.find(id)  // This is testable
}

// RSC (not directly testable)
export default async function Page({ params }: { params: { id: string } }) {
  const data = await getPageData(params.id)  // Test this function instead
  return <ClientView data={data} />
}
```

## 10. Anti-Patterns

| Anti-Pattern | Problem |
|---|---|
| Testing implementation details | Tests break on refactor even when behaviour unchanged. Test what the user sees. |
| `getByTestId` everywhere | No accessibility signal — fails to catch ARIA regressions |
| Mocking the module under test | Tautological — you end up testing the mock |
| `fireEvent` instead of `userEvent` | Misses focus/hover/pointer events that real browsers fire |
| Shared mutable state between tests | Tests pass/fail depending on execution order |
| No `afterEach` cleanup | Stale DOM accumulates — false positives |

## 11. Quick Reference Checklist

- [ ] `@testing-library/jest-dom` imported in setup — enables custom matchers
- [ ] `userEvent.setup()` called once per test, not `fireEvent`
- [ ] `getByRole` used for interactive elements, `getByLabelText` for form fields
- [ ] MSW server starts/resets/closes in `beforeAll`/`afterEach`/`afterAll`
- [ ] Loading and error states explicitly tested
- [ ] No `getByTestId` unless added specifically for testing
- [ ] `renderHook` + `act` used for hook tests
- [ ] Inline snapshots preferred over file snapshots
- [ ] RSC logic extracted to pure functions for unit testing
- [ ] Coverage thresholds set in `vite.config.ts`
