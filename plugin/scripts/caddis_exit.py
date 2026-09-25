"""Shared exit-code scale for caddis scripts."""

CLEAN = 0
BLOCKED = 1
ADVISORY = 2
NOT_RUN = 3
ERROR = 4

MEANING = {
    CLEAN: "clean",
    BLOCKED: "blocked",
    ADVISORY: "advisory",
    NOT_RUN: "could not run",
    ERROR: "error or bad usage",
}
