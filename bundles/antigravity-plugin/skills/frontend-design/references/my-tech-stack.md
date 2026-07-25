# My Technical Standards & Architecture Patterns

This document serves as the technical reference for all frontend implementation. When building components or pages, follow these structural patterns to ensure performance, stability, and clean code.

## 1. Component Patterns

### Composition Over Inheritance
Build flexible UIs by composing small, focused components rather than deep inheritance chains.

```
export function Card({ children, variant = 'default' }) {
  return <div className={`card card-${variant}`}>{children}</div>
}

export function CardHeader({ children }) {
  return <div className="card-header">{children}</div>
}

// Usage: <Card><CardHeader>Title</CardHeader></Card>
```

### Compound Components
Share implicit state between related components via context to keep logic encapsulated.

```
const TabsContext = createContext(undefined)

export function Tabs({ children, defaultTab }) {
  const [activeTab, setActiveTab] = useState(defaultTab)
  return (
    <TabsContext.Provider value={{ activeTab, setActiveTab }}>
      {children}
    </TabsContext.Provider>
  )
}

export function Tab({ id, children }) {
  const ctx = useContext(TabsContext)
  if (!ctx) throw new Error('Tab must be used within Tabs')
  return (
    <button 
      className={ctx.activeTab === id ? 'active' : ''} 
      onClick={() => ctx.setActiveTab(id)}
    >
      {children}
    </button>
  )
}
```

## 2. Custom Utility Hooks

```
// Debounce hook for search/expensive inputs
export function useDebounce(value, delay) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const handler = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(handler)
  }, [value, delay])
  return debounced
}

// Simplified toggle hook
export function useToggle(initial = false) {
  const [value, setValue] = useState(initial)
  const toggle = useCallback(() => setValue(v => !v), [])
  return [value, toggle]
}
```

## 3. Performance Optimization

### Memoization Rules
- Use `useMemo` for any data transformation or sorting of lists.
- Use `useCallback` for event handlers passed to components wrapped in `React.memo`.

```
// useMemo for expensive computations
const sorted = useMemo(() => items.sort((a, b) => b.score - a.score), [items])

// React.memo for pure leaf components
export const ItemCard = React.memo(({ item }) => (
  <div className="item-card"><h3>{item.name}</h3></div>
))
```

## 4. Accessibility Patterns

### Keyboard Navigation
Always handle key events for custom interactive widgets to ensure screen-reader and keyboard compatibility.

```
const handleKeyDown = (e) => {
  switch (e.key) {
    case 'ArrowDown': e.preventDefault(); setIndex(i => Math.min(i + 1, max)); break
    case 'ArrowUp': e.preventDefault(); setIndex(i => Math.max(i - 1, 0)); break
    case 'Enter': e.preventDefault(); onSelect(options[index]); break
    case 'Escape': onClose(); break
  }
}
```

## 5. Error Boundary Pattern
Wrap complex sections (like third-party widgets) in a safety net to prevent app crashes.

```
export class ErrorBoundary extends React.Component {
  state = { hasError: false, error: null }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-fallback">
          <h2>Something went wrong</h2>
          <button onClick={() => this.setState({ hasError: false })}>Try again</button>
        </div>
      )
    }
    return this.props.children
  }
}
```