
---

## FastAPI specifics
- **Async all the way.** `async def` routes; `await` I/O. Use async DB drivers/engines.
- **Routers stay thin.** A router validates input, calls a service/repository, returns a DTO. No SQL,
  no business logic in routers.
- **Typed boundaries.** Every endpoint has a Pydantic request model (if it takes a body) and a Pydantic
  response model (`response_model=`). No bare `dict` returns for non-trivial payloads.
- **Client-reachable paths.** Mount routers so the path a client calls actually reaches the server
  (consistent prefix, e.g. `/api`, matching any dev proxy). Confirm new routes are proxied.
- **Dependencies are injectable and overrideable** — design checks/clients as FastAPI dependencies so
  tests can `app.dependency_overrides` them (keeps the suite free of real external services).

Skills (caddis plugin, by name): `fastapi-dev`, `api-design`.
