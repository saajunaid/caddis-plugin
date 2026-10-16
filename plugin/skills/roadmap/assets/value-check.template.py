#!/usr/bin/env python3
"""Value check template: compare figures from an endpoint with an independent source over a fixed past window.

Copy it into the app (for example scripts/check_values.py) so CI and prod checks can run it again.

    python value-check.template.py --base http://localhost:8000 --expected expected.json
    python value-check.template.py --base http://localhost:8000 --expected expected.json --prove-it-can-fail

Expected file:
    {"window": {"start": "2026-09-01", "end": "2026-09-30"},
     "figures": [{"name": "...", "endpoint": "/api/x", "path": "a.b", "expected": 1200,
                  "source": "where the expected value came from", "population": "who is counted",
                  "denominator": "what the rate divides by, or none", "tolerance": 0.001, "series": "day"}]}

Rules:
  - The window must end before today. A moving window ("today") gives a number that changes while you check it.
  - Every figure names its source, population and denominator.
  - A "series": "day" figure has ISO date keys that all fall on one weekday. A weekday gap is not a data gap.
  - --prove-it-can-fail changes the expected values on purpose. The run must then exit 1.

Exit codes: 0 all figures pass, 1 a figure fails, 4 bad input or an HTTP error that is not a figure failure.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

_MISSING = object()


class BadInput(Exception):
    """The expected file or the request is wrong. Exit 4."""


def _parse_date(text: str, what: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(text))
    except ValueError as exc:
        raise BadInput(f"{what} is not an ISO date: {text!r}") from exc


def validate(spec: dict) -> None:
    window = spec.get("window") or {}
    start, end = _parse_date(window.get("start"), "window.start"), _parse_date(window.get("end"), "window.end")
    if end >= dt.date.today():
        raise BadInput(f"window.end {end} is not before today ({dt.date.today()}): use a fixed past window")
    if start > end:
        raise BadInput("window.start is after window.end")
    figures = spec.get("figures") or []
    if not figures:
        raise BadInput("no figures in the expected file")
    for fig in figures:
        name = fig.get("name") or "<unnamed>"
        for key in ("name", "endpoint", "path", "expected"):
            if key not in fig or fig[key] in ("", None):
                raise BadInput(f"figure {name!r} has no {key}")
        for key in ("source", "population", "denominator"):
            if not str(fig.get(key, "")).strip():
                raise BadInput(f"figure {name!r} has an empty {key}: name it")
        if fig.get("series") == "day":
            if not isinstance(fig["expected"], dict) or not fig["expected"]:
                raise BadInput(f"figure {name!r}: a day series needs a non-empty object of date keys")
            weekdays = {_parse_date(k, f"figure {name!r} key").weekday() for k in fig["expected"]}
            if len(weekdays) > 1:
                raise BadInput(f"figure {name!r}: day series keys fall on more than one weekday")


def prove_it_can_fail(spec: dict) -> dict:
    """Return a copy with a wrong expected value, so a correct endpoint must fail."""
    spec = copy.deepcopy(spec)
    scalars = [f for f in spec["figures"] if not isinstance(f["expected"], dict)]
    if scalars:
        scalars[0]["expected"] = scalars[0]["expected"] + 1
    series = [f for f in spec["figures"] if isinstance(f["expected"], dict)]
    if series:
        series[0]["expected"].pop(next(iter(series[0]["expected"])))  # a missing date must fail the compare
        series[0]["expected"]["1999-01-04"] = 0  # 1999-01-04 is a Monday; the endpoint has no such key
    if not scalars and not series:
        spec["figures"][0]["path"] += ".missing"
    return spec


def fetch(base: str, endpoint: str, window: dict, headers: dict) -> tuple[int, object]:
    query = urllib.parse.urlencode({"start": window["start"], "end": window["end"]})
    req = urllib.request.Request(f"{base.rstrip('/')}{endpoint}?{query}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise BadInput(f"cannot read {endpoint}: {exc}") from exc


def dig(data: object, path: str) -> object:
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return _MISSING
    return data


def same(actual: object, expected: object, tolerance: float) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and same(actual[k], v, tolerance) for k, v in expected.items())
    if isinstance(expected, bool) or isinstance(actual, bool) or not isinstance(expected, (int, float)):
        return actual == expected
    return isinstance(actual, (int, float)) and abs(actual - expected) <= tolerance


def check(spec: dict, base: str, headers: dict) -> bool:
    ok = True
    for fig in spec["figures"]:
        status, body = fetch(base, fig["endpoint"], spec["window"], headers)
        actual = dig(body, fig["path"]) if status == 200 else _MISSING
        passed = actual is not _MISSING and same(actual, fig["expected"], float(fig.get("tolerance", 0)))
        shown = "missing" if actual is _MISSING else actual
        if status != 200:
            shown = f"HTTP {status}"
        print(f"{'PASS' if passed else 'FAIL'} {fig['name']}: endpoint {shown} vs {fig['source']} {fig['expected']}; "
              f"population {fig['population']}; denominator {fig['denominator']}")
        ok = ok and passed
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", required=True, help="origin of the app, for example http://localhost:8000")
    ap.add_argument("--expected", required=True, help="expected figures JSON file")
    ap.add_argument("--prove-it-can-fail", action="store_true", help="change the expected values; the run must exit 1")
    ap.add_argument("--header", action="append", default=[], metavar="K:V", help="extra request header (repeatable)")
    args = ap.parse_args(argv)
    try:
        with open(args.expected, encoding="utf-8") as fh:
            spec = json.load(fh)
        validate(spec)
        headers = {}
        for h in args.header:
            key, sep, value = h.partition(":")
            if not sep:
                raise BadInput(f"--header needs K:V, got {h!r}")
            headers[key.strip()] = value.strip()
        if args.prove_it_can_fail:
            spec = prove_it_can_fail(spec)
        return 0 if check(spec, args.base, headers) else 1
    except (BadInput, OSError, ValueError) as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
