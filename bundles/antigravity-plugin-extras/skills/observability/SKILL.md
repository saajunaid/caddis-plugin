---
name: observability
description: Structured logging, OpenTelemetry distributed tracing, metrics (RED method), health checks, and error tracking with Sentry. Use for structured logs, correlation IDs, PII redaction, OpenTelemetry setup, distributed tracing, metrics counters/histograms/gauges, SLO-based alerting, liveness/readiness probes, or Sentry integration. Dual Python/TypeScript examples throughout.
---

# Observability Skill

Everything needed to understand what your system is doing in production: structured logging, distributed tracing, metrics, and error tracking.

## 1. Structured Logging

### Core Principles
- Emit JSON that machines can parse, not prose that humans must parse
- Every log line: `timestamp`, `level`, `message`, `correlation_id`, `service`
- Never log PII — redact before logging
- Use log levels semantically (DEBUG/INFO/WARNING/ERROR — no `print()`)

### Python — `structlog` or `loguru`
```python
# structlog (recommended for services)
import structlog
import uuid

logger = structlog.get_logger()

# Configure at app startup
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

# Bind context for a request/task
structlog.contextvars.bind_contextvars(
    correlation_id=str(uuid.uuid4()),
    user_id=user.id,          # Safe — internal ID, not PII
    service="user-service",
)

logger.info("user.login", method="oauth2", provider="google")
logger.warning("rate.limit.approaching", remaining=5, limit=100)
logger.error("db.query.failed", query="users.find", error=str(e))
```

```python
# loguru (recommended for simpler scripts/notebooks)
from loguru import logger
import sys

logger.remove()  # Remove default stderr handler
logger.add(
    sys.stderr,
    format="{time:ISO8601} {level} {message}",
    serialize=True,            # JSON output
    level="INFO",
)
logger.add("logs/app.log", rotation="100 MB", retention="7 days", serialize=True)
```

### TypeScript — `pino`
```ts
import pino from 'pino'

export const logger = pino({
  level: process.env.LOG_LEVEL ?? 'info',
  transport: process.env.NODE_ENV === 'development'
    ? { target: 'pino-pretty', options: { colorize: true } }
    : undefined,
  base: { service: 'web-api', env: process.env.NODE_ENV },
})

// Child logger with bound context
export function requestLogger(correlationId: string) {
  return logger.child({ correlationId })
}
```

### PII Redaction
```python
# Python — never log these fields
REDACT_KEYS = {'password', 'token', 'secret', 'credit_card', 'ssn', 'dob', 'email', 'phone'}

def safe_log(data: dict) -> dict:
    return {k: '***' if k in REDACT_KEYS else v for k, v in data.items()}
```

```ts
// pino built-in redaction
const logger = pino({ redact: ['password', 'authorization', 'cookie', '*.token', '*.secret'] })
```

## 2. Correlation IDs

Every entry point generates a `correlation_id` and attaches it to all downstream calls.

```python
# FastAPI middleware
import uuid
from fastapi import Request
import structlog

async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response
```

```ts
// Next.js middleware
import { NextResponse } from 'next/server'
import { randomUUID } from 'node:crypto'

export function middleware(request: Request) {
  const correlationId = request.headers.get('x-correlation-id') ?? randomUUID()
  const response = NextResponse.next()
  response.headers.set('x-correlation-id', correlationId)
  return response
}
```

## 3. OpenTelemetry — Distributed Tracing

### Python Setup
```python
# pip install opentelemetry-sdk opentelemetry-exporter-otlp opentelemetry-instrumentation-fastapi

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Configure tracer
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel-collector:4317")))
trace.set_tracer_provider(provider)

# Auto-instrument FastAPI
FastAPIInstrumentor.instrument_app(app)

# Manual span creation
tracer = trace.get_tracer(__name__)

async def process_order(order_id: str):
    with tracer.start_as_current_span("process_order") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("order.source", "api")
        
        try:
            result = await db.fetch_order(order_id)
            span.set_attribute("order.status", result.status)
            return result
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise
```

### TypeScript Setup
```ts
// npm install @opentelemetry/sdk-node @opentelemetry/auto-instrumentations-node @opentelemetry/exporter-trace-otlp-http

// instrumentation.ts (Next.js) or tracing.ts (Node)
import { NodeSDK } from '@opentelemetry/sdk-node'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node'

const sdk = new NodeSDK({
  serviceName: process.env.OTEL_SERVICE_NAME ?? 'my-service',
  traceExporter: new OTLPTraceExporter({ url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT }),
  instrumentations: [getNodeAutoInstrumentations()],
})
sdk.start()
```

### Span Naming Convention
- Format: `{noun}.{verb}` — e.g., `order.process`, `user.authenticate`, `db.query`
- Include resource IDs as span attributes, not in the span name
- Group spans by service domain: `payment.*`, `inventory.*`

## 4. Metrics — RED Method

**Rate, Error rate, Duration** — the minimal viable signal for every service endpoint.

```python
# Python — prometheus_client (or OpenTelemetry Metrics)
from prometheus_client import Counter, Histogram, Gauge, start_http_server

REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code'],
)
REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration',
    ['method', 'endpoint'],
    buckets=[0.005, 0.01, 0.05, 0.1, 0.5, 1, 2.5, 5],
)
ACTIVE_CONNECTIONS = Gauge('active_connections', 'Active connections')

# FastAPI middleware
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    import time
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code,
    ).inc()
    REQUEST_DURATION.labels(
        method=request.method,
        endpoint=request.url.path,
    ).observe(duration)
    return response
```

### Metric Types
| Type | Use For | Examples |
|---|---|---|
| **Counter** | Things that only go up | Requests served, errors, events processed |
| **Histogram** | Distribution of values | Request duration, payload size, DB query time |
| **Gauge** | Values that go up and down | Active connections, queue depth, memory usage |

## 5. Health Checks — Liveness vs Readiness

```python
# FastAPI health endpoints
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

@app.get("/health/live")
async def liveness():
    """I am alive and not in a broken state. Restart me if this fails."""
    return {"status": "ok"}

@app.get("/health/ready")
async def readiness():
    """I am ready to serve traffic. Remove from load balancer if this fails."""
    checks = {}

    # Check DB connection
    try:
        await db.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Check cache
    try:
        await redis.ping()
        checks["cache"] = "ok"
    except Exception as e:
        checks["cache"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )
```

| Probe | When Fails | Action |
|---|---|---|
| **Liveness** | App is deadlocked or crashed | Kubernetes/platform restarts the pod |
| **Readiness** | App can't handle traffic (DB down, warming up) | Remove from load balancer pool, don't restart |

## 6. Error Tracking — Sentry

```python
# Python FastAPI
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

sentry_sdk.init(
    dsn=settings.SENTRY_DSN,
    environment=settings.APP_ENV,
    traces_sample_rate=0.1,           # 10% of transactions traced
    profiles_sample_rate=0.1,
    integrations=[FastApiIntegration(), SqlalchemyIntegration()],
    before_send=scrub_sensitive_data,  # Always scrub PII
)

def scrub_sensitive_data(event, hint):
    """Remove PII from Sentry events before sending."""
    if 'request' in event:
        event['request'].pop('cookies', None)
        if 'headers' in event['request']:
            event['request']['headers'].pop('Authorization', None)
    return event
```

```ts
// TypeScript Next.js — sentry.server.config.ts / sentry.client.config.ts
import * as Sentry from '@sentry/nextjs'

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NODE_ENV,
  tracesSampleRate: 0.1,
  beforeSend(event) {
    // Strip auth tokens from breadcrumbs
    event.breadcrumbs?.values?.forEach(b => {
      if (b.data?.['Authorization']) delete b.data['Authorization']
    })
    return event
  },
})
```

### Sentry Grouping — Good Fingerprinting
```python
with sentry_sdk.push_scope() as scope:
    scope.set_tag("order_id", order_id)
    scope.set_context("order", {"status": order.status, "items": len(order.items)})
    scope.fingerprint = ["order-processing-failure", order.error_type]
    sentry_sdk.capture_exception(e)
```

## 7. SLO-Based Alerting

```yaml
# Example Prometheus alerting rule
groups:
  - name: slo
    rules:
      - alert: HighErrorRate
        expr: |
          sum(rate(http_requests_total{status_code=~"5.."}[5m]))
          /
          sum(rate(http_requests_total[5m])) > 0.01
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "Error rate above 1% SLO for 5 minutes"

      - alert: SlowResponseTime
        expr: |
          histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 1.0
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "P95 response time above 1s SLO"
```

**Burn Rate**: Alert when error budget burns faster than expected, not just when a threshold is crossed momentarily. `for: 5m` prevents alert storms.

## 8. Checklist

- [ ] Structured JSON logs (not `print()`)
- [ ] Correlation IDs propagated as request header + bound to logger context
- [ ] PII fields redacted before logging (`password`, `token`, email, phone)
- [ ] OpenTelemetry SDK initialized before app starts
- [ ] Custom spans wrap business operations (not just framework auto-instrumentation)
- [ ] Span naming uses `{noun}.{verb}` convention
- [ ] RED metrics (rate, error rate, duration) instrumented for all HTTP endpoints
- [ ] `/health/live` and `/health/ready` endpoints implemented with different semantics
- [ ] Sentry DSN loaded from environment, not hardcoded
- [ ] Sentry `before_send` scrubs PII before sending
- [ ] Alerts fire on SLO burn rate, not just raw thresholds
