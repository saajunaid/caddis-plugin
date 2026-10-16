"""Shared exit-code scale for caddis scripts."""

CLEAN = 0
BLOCKED = 1
ADVISORY = 2
NOT_RUN = 3
ERROR = 4
ROUND_LIMIT = 5  # caddis_review.py --plan: round limit reached, stop, the owner decides

MEANING = {
    CLEAN: "clean",
    BLOCKED: "blocked",
    ADVISORY: "advisory",
    NOT_RUN: "could not run",
    ERROR: "error or bad usage",
    ROUND_LIMIT: "round limit reached, the owner decides",
}
