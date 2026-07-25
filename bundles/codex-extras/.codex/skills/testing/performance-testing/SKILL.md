---
name: performance-testing
description: Performance testing, load testing, and benchmarking for APIs, databases, and web applications. Use when planning load tests, setting performance budgets, profiling bottlenecks, or validating scalability. Covers Locust, k6, pytest-benchmark, browser performance, and database query profiling.
---

# Performance Testing Skill

Measure before you optimise. This skill covers how to define performance budgets, write load tests, benchmark critical paths, and profile bottlenecks.

## 1. When to Apply This Skill

**Trigger conditions:**
- "How will this perform under load?"
- "We need load testing"
- "Set performance budgets"
- "Profile this slow endpoint"
- Pre-launch performance validation
- After performance incidents or SLA breaches

## 2. Performance Budget Template

Define budgets before testing. Every metric needs a target.

```markdown
# Performance Budget: {Service/Feature}

## Response Time Targets
| Endpoint / Action | p50 | p95 | p99 | Max |
|-------------------|-----|-----|-----|-----|
| GET /api/items | <100ms | <250ms | <500ms | <1s |
| POST /api/orders | <200ms | <500ms | <1s | <2s |
| Dashboard page load | <1.5s | <3s | <5s | <8s |

## Throughput Targets
| Scenario | Target RPS | Concurrent Users |
|----------|-----------|-----------------|
| Normal load | 100 rps | 50 |
| Peak load | 500 rps | 200 |
| Stress test | 1000 rps | 500 |

## Resource Limits
| Resource | Threshold |
|----------|-----------|
| CPU | <70% at normal load |
| Memory | <80% at peak load |
| DB connections | <80% of pool size |
| Error rate | <0.1% at normal load |
```

## 3. Load Testing with Locust (Python)

```python
from locust import HttpUser, task, between

class APIUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def list_items(self):
        self.client.get("/api/items", name="GET /api/items")

    @task(1)
    def create_item(self):
        self.client.post(
            "/api/items",
            json={"name": "test", "value": 42},
            name="POST /api/items",
        )

    def on_start(self):
        """Authenticate once per simulated user."""
        resp = self.client.post("/api/auth/login", json={
            "username": "loadtest",
            "password": "test-password",  # Use env var in real tests
        })
        self.client.headers["Authorization"] = f"Bearer {resp.json()['token']}"
```

Run: `locust -f load_test.py --host=http://localhost:8000 --users=100 --spawn-rate=10`

## 4. Load Testing with k6 (JavaScript)

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '1m', target: 50 },   // Ramp up
    { duration: '3m', target: 50 },   // Sustain
    { duration: '1m', target: 200 },  // Peak
    { duration: '2m', target: 200 },  // Sustain peak
    { duration: '1m', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    http_req_failed: ['rate<0.01'],
  },
};

export default function () {
  const res = http.get('http://localhost:8000/api/items');
  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });
  sleep(1);
}
```

## 5. Python Benchmarking with pytest-benchmark

```python
import pytest

def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

def test_fibonacci_benchmark(benchmark):
    result = benchmark(fibonacci, 100)
    assert result == 354224848179261915075
```

Run: `pytest --benchmark-only --benchmark-sort=mean`

## 6. Database Query Profiling

### SQL Server
```sql
-- Enable actual execution plan + IO statistics
SET STATISTICS IO ON;
SET STATISTICS TIME ON;

-- Run the slow query
SELECT ...

-- Check for table scans, missing indexes
-- Key metrics: logical reads, CPU time, elapsed time
```

### Python profiling with cProfile
```python
import cProfile
import pstats

def profile_function(func, *args):
    """Profile a function and print top 20 cumulative time entries."""
    profiler = cProfile.Profile()
    profiler.enable()
    result = func(*args)
    profiler.disable()

    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    stats.print_stats(20)
    return result
```

## 7. Browser Performance Testing

### Core Web Vitals Targets

| Metric | Good | Needs Improvement | Poor |
|--------|------|-------------------|------|
| LCP (Largest Contentful Paint) | ≤2.5s | ≤4.0s | >4.0s |
| INP (Interaction to Next Paint) | ≤200ms | ≤500ms | >500ms |
| CLS (Cumulative Layout Shift) | ≤0.1 | ≤0.25 | >0.25 |

### Lighthouse CI Check
```bash
npx @lhci/cli autorun --collect.url=http://localhost:3000 \
  --assert.preset=lighthouse:recommended \
  --assert.assertions.categories:performance=error:minScore:0.9
```

## 8. Test Types and When to Use Them

| Type | Purpose | Tool | When |
|------|---------|------|------|
| **Load test** | Validate normal traffic capacity | Locust, k6 | Pre-launch, after scaling changes |
| **Stress test** | Find breaking point | k6 (ramping) | Capacity planning |
| **Soak test** | Detect memory leaks, connection exhaustion | Locust (long run) | Before major releases |
| **Spike test** | Validate autoscaling / recovery | k6 (sudden ramp) | Event-driven apps |
| **Benchmark** | Compare implementations | pytest-benchmark | During optimisation |
| **Profile** | Find hotspots | cProfile, py-spy | After identifying slow endpoint |

## 9. Reporting Template

```markdown
# Performance Test Report: {Date}

## Test Configuration
- Tool: {Locust/k6}
- Duration: {minutes}
- Peak users: {n}
- Environment: {staging/production-like}

## Results vs Budget
| Metric | Budget | Actual | Status |
|--------|--------|--------|--------|
| p95 response time | <500ms | {n}ms | ✅/❌ |
| Error rate | <0.1% | {n}% | ✅/❌ |
| Throughput | >100 rps | {n} rps | ✅/❌ |

## Bottlenecks Found
1. {description} — {root cause} — {recommendation}

## Recommendations
- {action items}
```

## 10. Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Testing against localhost only | Misses network latency, DNS, TLS | Test against staging environment |
| No warm-up phase | Cold caches skew results | Add 1-2 min ramp-up |
| Ignoring error rate | High throughput ≠ success | Always check error rate alongside latency |
| Single-metric focus | p50 looks fine but p99 is 10s | Report p50, p95, p99, and max |
| Testing with empty database | Production has millions of rows | Use production-sized test data |
| No baseline comparison | Can't tell if results are better/worse | Always compare against previous run |
