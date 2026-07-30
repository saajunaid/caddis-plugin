#!/usr/bin/env python3
"""Cold/warm HTTP timing harness for the dashboard-perf-sweep skill.

Given a base URL and a list of endpoints, measures a COLD request (first hit) and a WARM
request (immediately after) per endpoint, safely: a timeout or connection error on one endpoint
is recorded as a finding, never a crash of the whole sweep (DASHBOARD-PERFORMANCE-STANDARD.md
Rule 6 gate-1 mechanics; the huge cold/warm gap without a cache in between is itself diagnostic
of a query-shape problem, not a cache-TTL one).

This harness does NOT start dev servers or know anything about a specific app -- that's the
`run` skill's job. It only measures a URL that is already reachable. stdlib-only (urllib), no
install, matching the other caddis tool scripts (oss_review.py etc.).

CLI:
  python perf_sweep.py --base-url http://localhost:8000 --endpoints endpoints.json
  python perf_sweep.py --base-url http://localhost:8000 --endpoints endpoints.json --output report.json
  python perf_sweep.py --base-url http://localhost:8000 --endpoints endpoints.json --gate1-seconds 1.0

endpoints.json shape (a JSON list):
  [
    {"name": "Historical Trends chart", "method": "GET", "path": "/api/trends/daily"},
    {"name": "IW grid", "method": "POST", "path": "/raworkbench/investigation/query",
     "json": {"filters": {}}, "headers": {"Authorization": "Bearer ..."}}
  ]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_GATE1_SECONDS = 1.0  # DASHBOARD-PERFORMANCE-STANDARD.md Rule 6


@dataclass
class RequestResult:
    ok: bool
    status: int | None = None
    elapsed_ms: float | None = None
    error: str | None = None


@dataclass
class EndpointResult:
    name: str
    method: str
    path: str
    cold: RequestResult
    warm: RequestResult | None = None
    gate1_breach: bool = False


@dataclass
class SweepReport:
    base_url: str
    gate1_seconds: float
    endpoints: list[EndpointResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "gate1_seconds": self.gate1_seconds,
            "endpoints": [
                {
                    "name": e.name,
                    "method": e.method,
                    "path": e.path,
                    "cold": asdict(e.cold),
                    "warm": asdict(e.warm) if e.warm else None,
                    "gate1_breach": e.gate1_breach,
                }
                for e in self.endpoints
            ],
        }


def _do_request(
    url: str,
    method: str,
    *,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> RequestResult:
    """One timed HTTP request. Never raises -- a timeout/connection/HTTP error becomes a
    RequestResult with ok=False and a human-readable error, which is itself a sweep finding."""
    data = None
    req_headers = dict(headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return RequestResult(ok=True, status=resp.status, elapsed_ms=elapsed_ms)
    except urllib.error.HTTPError as exc:
        # An HTTP error status still completed a round trip -- timing is a real finding.
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return RequestResult(ok=False, status=exc.code, elapsed_ms=elapsed_ms, error=f"HTTP {exc.code}")
    except urllib.error.URLError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return RequestResult(ok=False, elapsed_ms=elapsed_ms, error=f"connection error: {exc.reason}")
    except TimeoutError:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return RequestResult(ok=False, elapsed_ms=elapsed_ms, error=f"timeout after {timeout}s")


def sweep_endpoint(
    base_url: str,
    endpoint: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    gate1_seconds: float = DEFAULT_GATE1_SECONDS,
    warm: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> EndpointResult:
    method = endpoint.get("method", "GET").upper()
    path = endpoint["path"]
    url = base_url.rstrip("/") + path
    headers = dict(extra_headers or {})
    headers.update(endpoint.get("headers", {}))
    json_body = endpoint.get("json")

    cold = _do_request(url, method, json_body=json_body, headers=headers, timeout=timeout)
    warm_result = None
    if warm:
        warm_result = _do_request(url, method, json_body=json_body, headers=headers, timeout=timeout)

    gate1_breach = bool(cold.ok and cold.elapsed_ms is not None and cold.elapsed_ms / 1000.0 > gate1_seconds)
    return EndpointResult(
        name=endpoint.get("name", path),
        method=method,
        path=path,
        cold=cold,
        warm=warm_result,
        gate1_breach=gate1_breach,
    )


def sweep(
    base_url: str,
    endpoints: list[dict[str, Any]],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    gate1_seconds: float = DEFAULT_GATE1_SECONDS,
    warm: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> SweepReport:
    report = SweepReport(base_url=base_url, gate1_seconds=gate1_seconds)
    for endpoint in endpoints:
        report.endpoints.append(
            sweep_endpoint(
                base_url,
                endpoint,
                timeout=timeout,
                gate1_seconds=gate1_seconds,
                warm=warm,
                extra_headers=extra_headers,
            )
        )
    return report


def format_report(report: SweepReport) -> str:
    lines = [f"Sweep: {report.base_url}  (gate 1 = {report.gate1_seconds}s cold, uncached)", ""]
    for e in report.endpoints:
        if not e.cold.ok:
            lines.append(f"  [ERROR]  {e.method:5s} {e.path:45s}  {e.cold.error}")
            continue
        flag = "SLOW " if e.gate1_breach else "     "
        cold_s = f"{e.cold.elapsed_ms:8.1f}ms"
        warm_s = f"{e.warm.elapsed_ms:8.1f}ms" if e.warm and e.warm.ok else "n/a"
        gap = ""
        if e.warm and e.warm.ok and e.cold.elapsed_ms and e.warm.elapsed_ms:
            ratio = e.cold.elapsed_ms / max(e.warm.elapsed_ms, 0.01)
            if ratio > 3:
                gap = f"  (cold/warm {ratio:.1f}x -- likely query-shape, not cache-TTL)"
        lines.append(f"  {flag}{e.method:5s} {e.path:45s}  cold={cold_s}  warm={warm_s}{gap}")
    breaches = [e for e in report.endpoints if e.gate1_breach]
    errors = [e for e in report.endpoints if not e.cold.ok]
    problems = breaches + errors
    lines.append("")
    lines.append(
        f"{len(problems)}/{len(report.endpoints)} endpoint(s) have a problem "
        f"({len(breaches)} slow, {len(errors)} errored/timed out -- a timeout is a WORSE "
        f"signal than a gate-1 breach, not a lesser one)."
    )
    if problems:
        lines.append("Not itself a rs-kit verdict -- apply the shape checklist (SKILL.md) next.")
    return "\n".join(lines)


def _parse_header(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise argparse.ArgumentTypeError(f"--header must be 'Key: Value', got {value!r}")
    key, _, val = value.partition(":")
    return key.strip(), val.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True, help="e.g. http://localhost:8703")
    parser.add_argument("--endpoints", required=True, help="path to a JSON file (see module docstring)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--gate1-seconds", type=float, default=DEFAULT_GATE1_SECONDS)
    parser.add_argument("--no-warm", action="store_true", help="skip the warm (second) request")
    parser.add_argument("--header", action="append", default=[], type=_parse_header,
                         help="extra header applied to every request, repeatable: --header 'Cookie: session=...'")
    parser.add_argument("--output", help="also write the JSON report to this path")
    args = parser.parse_args(argv)

    with open(args.endpoints, encoding="utf-8") as f:
        endpoints = json.load(f)
    if not isinstance(endpoints, list):
        print(f"[FAIL] {args.endpoints} must contain a JSON list of endpoint objects", file=sys.stderr)
        return 2

    report = sweep(
        args.base_url,
        endpoints,
        timeout=args.timeout,
        gate1_seconds=args.gate1_seconds,
        warm=not args.no_warm,
        extra_headers=dict(args.header),
    )

    print(format_report(report))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nWrote {args.output}")

    breaches = [e for e in report.endpoints if e.gate1_breach]
    errors = [e for e in report.endpoints if not e.cold.ok]
    return 1 if (breaches or errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
