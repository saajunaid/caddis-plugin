---
name: backend-development
description: Backend API design, database architecture, microservices patterns, and test-driven development. Use for designing APIs, database schemas, or backend system architecture.
source: wshobson/agents
license: MIT
---

# Backend Development

## API Design

### RESTful Conventions
```
GET    /users          # List users
POST   /users          # Create user
GET    /users/:id      # Get user
PUT    /users/:id      # Update user (full)
PATCH  /users/:id      # Update user (partial)
DELETE /users/:id      # Delete user

GET    /users/:id/posts  # List user's posts
POST   /users/:id/posts  # Create post for user
```

### Response Format
```json
{
  "data": { ... },
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 100
  }
}
```

### Error Format
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input",
    "details": [
      { "field": "email", "message": "Invalid format" }
    ]
  }
}
```

## Database Patterns

### Schema Design
```sql
-- Use UUIDs for public IDs
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  public_id UUID DEFAULT gen_random_uuid() UNIQUE,
  email VARCHAR(255) UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Soft deletes
ALTER TABLE users ADD COLUMN deleted_at TIMESTAMPTZ;

-- Indexes
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_created ON users(created_at DESC);
```

### Query Patterns
```sql
-- Pagination with cursor
SELECT * FROM posts
WHERE created_at < $cursor
ORDER BY created_at DESC
LIMIT 20;

-- Efficient counting
SELECT reltuples::bigint AS estimate
FROM pg_class WHERE relname = 'users';
```

## Authentication

### JWT Pattern
```typescript
interface TokenPayload {
  sub: string;      // User ID
  iat: number;      // Issued at
  exp: number;      // Expiration
  scope: string[];  // Permissions
}

function verifyToken(token: string): TokenPayload {
  return jwt.verify(token, SECRET) as TokenPayload;
}
```

### Middleware
```typescript
async function authenticate(req: Request, res: Response, next: Next) {
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (!token) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  try {
    req.user = verifyToken(token);
    next();
  } catch {
    res.status(401).json({ error: 'Invalid token' });
  }
}
```

## Caching Strategy

```typescript
// Cache-aside pattern
async function getUser(id: string): Promise<User> {
  const cached = await redis.get(`user:${id}`);
  if (cached) return JSON.parse(cached);

  const user = await db.users.findById(id);
  await redis.setex(`user:${id}`, 3600, JSON.stringify(user));
  return user;
}

// Cache invalidation
async function updateUser(id: string, data: Partial<User>) {
  await db.users.update(id, data);
  await redis.del(`user:${id}`);
}
```

## Architecture Patterns

### Repository Pattern
Abstract data access from business logic for testability and swappable backends.

```typescript
interface UserRepository {
  findAll(filters?: UserFilters): Promise<User[]>
  findById(id: string): Promise<User | null>
  create(data: CreateUserDto): Promise<User>
  update(id: string, data: UpdateUserDto): Promise<User>
  delete(id: string): Promise<void>
}
```

### Service Layer Pattern
Separate business logic from data access and HTTP concerns.

```typescript
class UserService {
  constructor(private userRepo: UserRepository) {}

  async createUser(data: CreateUserDto): Promise<User> {
    // Business logic: validation, enrichment, side effects
    const existing = await this.userRepo.findByEmail(data.email);
    if (existing) throw new ConflictError('Email already registered');
    return this.userRepo.create(data);
  }
}
```

### N+1 Query Prevention
```typescript
// Bad: N+1 queries
const posts = await getPosts();
for (const post of posts) {
  post.author = await getUser(post.author_id);  // N queries
}

// Good: Batch fetch
const posts = await getPosts();
const authorIds = posts.map(p => p.author_id);
const authors = await getUsers(authorIds);  // 1 query
const authorMap = new Map(authors.map(a => [a.id, a]));
posts.forEach(post => { post.author = authorMap.get(post.author_id); });
```

## Rate Limiting

```typescript
// Library-based approach
const limiter = rateLimit({
  windowMs: 60 * 1000,  // 1 minute
  max: 100,             // 100 requests per window
  keyGenerator: (req) => req.ip,
  handler: (req, res) => {
    res.status(429).json({ error: 'Too many requests' });
  }
});
```

## Error Handling

### Retry with Exponential Backoff
```typescript
async function fetchWithRetry<T>(
  fn: () => Promise<T>,
  maxRetries = 3
): Promise<T> {
  let lastError: Error;
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error as Error;
      if (i < maxRetries - 1) {
        const delay = Math.pow(2, i) * 1000;
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
  }
  throw lastError!;
}
```

### Centralized Error Handler
```typescript
class ApiError extends Error {
  constructor(public statusCode: number, message: string, public isOperational = true) {
    super(message);
  }
}

function errorHandler(error: unknown, req: Request): Response {
  if (error instanceof ApiError) {
    return json({ error: error.message }, { status: error.statusCode });
  }
  if (error instanceof z.ZodError) {
    return json({ error: 'Validation failed', details: error.errors }, { status: 400 });
  }
  console.error('Unexpected error:', error);
  return json({ error: 'Internal server error' }, { status: 500 });
}
```

## Role-Based Access Control

```typescript
type Permission = 'read' | 'write' | 'delete' | 'admin';

const rolePermissions: Record<string, Permission[]> = {
  admin: ['read', 'write', 'delete', 'admin'],
  moderator: ['read', 'write', 'delete'],
  user: ['read', 'write']
};

function hasPermission(user: { role: string }, permission: Permission): boolean {
  return (rolePermissions[user.role] || []).includes(permission);
}
```

## Background Jobs and Queues

```typescript
class JobQueue<T> {
  private queue: T[] = [];
  private processing = false;

  async add(job: T): Promise<void> {
    this.queue.push(job);
    if (!this.processing) this.process();
  }

  private async process(): Promise<void> {
    this.processing = true;
    while (this.queue.length > 0) {
      const job = this.queue.shift()!;
      try { await this.execute(job); }
      catch (error) { console.error('Job failed:', error); }
    }
    this.processing = false;
  }

  private async execute(job: T): Promise<void> { /* implementation */ }
}
```

## Observability

### Structured Logging
```typescript
class Logger {
  log(level: 'info' | 'warn' | 'error', message: string, context?: Record<string, unknown>) {
    console.log(JSON.stringify({
      timestamp: new Date().toISOString(), level, message, ...context
    }));
  }
  info(msg: string, ctx?: Record<string, unknown>) { this.log('info', msg, ctx); }
  warn(msg: string, ctx?: Record<string, unknown>) { this.log('warn', msg, ctx); }
  error(msg: string, err: Error, ctx?: Record<string, unknown>) {
    this.log('error', msg, { ...ctx, error: err.message, stack: err.stack });
  }
}
```

### Health and Monitoring
- **Metrics**: Request latency, error rates, queue depths
- **Tracing**: Distributed tracing with correlation IDs
- **Health checks**: `/health` and `/ready` endpoints
