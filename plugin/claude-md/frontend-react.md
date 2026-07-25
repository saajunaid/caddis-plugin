# Frontend (`frontend/`) — conventions

Scope: React + TypeScript SPA. Inherits all root laws (TDD included).

## Rules
- **Server state = a query library** (e.g. TanStack Query). Data fetching goes through a `use<Thing>`
  hook that calls a typed function in `services/`. No ad-hoc `useEffect`+`useState` fetching.
- **Client state = a light store** (e.g. Zustand) for UI toggles/filters/theme.
- **Types are the contract.** API response types in `services/`/`types/` must match the backend response
  models exactly. When the backend DTO changes, update the TS type in the same change.
- **UI from the project's primitives** (e.g. shadcn/Radix + Tailwind). Compose from `components/ui/`;
  use the class-merge helper. Don't introduce a parallel styling system.
- **Routing** per the project's router (typed params; don't cast).
- **Handle all query states** in data-backed components: loading, error, and empty — not just success.

## Adding a data-backed UI element (the path)
1. Failing component/hook test first (e.g. Vitest + Testing Library) — see `tests/CLAUDE.md`.
2. Type + fetch fn in `services/`.
3. `use<Thing>` hook wrapping the query library.
4. Component composed from `components/ui/`.
5. `npm test` → green. `npm run build` to typecheck.

Skills (caddis plugin, by name): `react-best-practices`, `shadcn-radix`, `css-architecture`.
