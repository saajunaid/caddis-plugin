---
name: react-best-practices
description: Modern React development guidelines covering hooks, component patterns, state management, performance optimization, and TypeScript integration.
---

# React Best Practices

Modern React development guidelines for building maintainable, performant applications.

## When to Use

- Building React applications (Next.js, Vite, CRA)
- Reviewing React code for quality
- Optimizing React app performance
- Learning modern React patterns (hooks, server components)

---

## Steps

### Step 1: Component Structure

#### Functional Components Only

```tsx
// Prefer: Arrow function with explicit return type
const UserCard: React.FC<UserCardProps> = ({ name, email, avatar }) => {
  return (
    <div className="user-card">
      <img src={avatar} alt={`${name}'s avatar`} />
      <h3>{name}</h3>
      <p>{email}</p>
    </div>
  );
};

// Props interface (always define)
interface UserCardProps {
  name: string;
  email: string;
  avatar: string;
  onSelect?: (email: string) => void;
}
```

#### File Organization

```
src/
├── components/       # Reusable UI components
│   ├── Button/
│   │   ├── Button.tsx
│   │   ├── Button.test.tsx
│   │   └── index.ts
│   └── ...
├── hooks/            # Custom hooks
├── pages/            # Route-level components
├── services/         # API calls
├── types/            # Shared TypeScript types
└── utils/            # Utility functions
```

### Step 2: Hooks Patterns

#### useState -- Keep State Minimal

```tsx
// Good: derive values instead of storing them
const [items, setItems] = useState<Item[]>([]);
const totalPrice = items.reduce((sum, item) => sum + item.price, 0); // Derived

// Bad: redundant state
const [items, setItems] = useState<Item[]>([]);
const [totalPrice, setTotalPrice] = useState(0); // Don't do this
```

#### useEffect -- Cleanup and Dependencies

```tsx
useEffect(() => {
  const controller = new AbortController();

  async function fetchData() {
    try {
      const res = await fetch(`/api/users/${userId}`, { signal: controller.signal });
      const data = await res.json();
      setUser(data);
    } catch (err) {
      if (!controller.signal.aborted) setError(err);
    }
  }

  fetchData();
  return () => controller.abort(); // Cleanup
}, [userId]); // Only re-run when userId changes
```

#### Custom Hooks -- Extract Logic

```tsx
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}

// Usage
const debouncedSearch = useDebounce(searchTerm, 300);
```

### Step 3: State Management

#### Local State (useState) -- Default Choice

Use for: form inputs, toggle states, component-specific data.

#### Context -- Shared UI State

```tsx
const ThemeContext = createContext<ThemeContextType | null>(null);

function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
```

Use for: theme, auth status, locale. **Not for** frequently changing data.

#### External Store (Zustand/Redux) -- Complex State

Use for: shopping cart, multi-step forms, real-time data.

```tsx
// Zustand example (lightweight)
const useStore = create<StoreState>((set) => ({
  items: [],
  addItem: (item) => set((state) => ({ items: [...state.items, item] })),
  removeItem: (id) => set((state) => ({ items: state.items.filter((i) => i.id !== id) })),
}));
```

### Step 4: Performance Optimization

#### Memoization (use sparingly)

```tsx
// React.memo -- prevent re-renders when props haven't changed
const ExpensiveList = React.memo(({ items }: { items: Item[] }) => {
  return items.map((item) => <ListItem key={item.id} item={item} />);
});

// useMemo -- cache expensive computations
const sortedItems = useMemo(
  () => items.sort((a, b) => a.name.localeCompare(b.name)),
  [items]
);

// useCallback -- stable function references for child components
const handleClick = useCallback((id: string) => {
  setSelected(id);
}, []);
```

#### Lazy Loading

```tsx
const Dashboard = React.lazy(() => import("./pages/Dashboard"));

function App() {
  return (
    <Suspense fallback={<LoadingSpinner />}>
      <Dashboard />
    </Suspense>
  );
}
```

#### Virtualization for Large Lists

```tsx
import { FixedSizeList } from "react-window";

<FixedSizeList height={400} itemCount={10000} itemSize={35} width="100%">
  {({ index, style }) => <div style={style}>{items[index].name}</div>}
</FixedSizeList>
```

### Step 5: Error Handling

```tsx
class ErrorBoundary extends React.Component<Props, State> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("React error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return <div>Something went wrong. Please refresh.</div>;
    }
    return this.props.children;
  }
}
```

---

## Patterns and Examples

### Data Fetching Pattern (with loading/error states)

```tsx
function useQuery<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetch(url, { signal: controller.signal })
      .then((res) => res.json())
      .then(setData)
      .catch((err) => !controller.signal.aborted && setError(err))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [url]);

  return { data, loading, error };
}
```

### Conditional Rendering

```tsx
// Early return for loading/error
if (loading) return <Skeleton />;
if (error) return <ErrorMessage error={error} />;
if (!data?.length) return <EmptyState message="No items found" />;

return <ItemList items={data} />;
```

---

## Checklist

- [ ] All components are functional (no class components unless ErrorBoundary)
- [ ] Props have TypeScript interfaces
- [ ] Custom hooks extract reusable logic
- [ ] useEffect has proper cleanup and dependencies
- [ ] State is minimal (derive values, don't duplicate)
- [ ] Memoization used only where measured benefit exists
- [ ] Large lists use virtualization
- [ ] Error boundaries wrap key sections
- [ ] Loading and empty states handled
- [ ] Keys are stable (not array index for dynamic lists)
