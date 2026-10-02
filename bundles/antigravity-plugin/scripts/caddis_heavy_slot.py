"""Heavy-run slot manager.

Limits concurrent test-heavy runs (test suites, gates) using non-blocking OS byte locks.
"""

from __future__ import annotations

import contextlib
import datetime
import errno
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class HeavySlotBusy(Exception):
    """Raised when all heavy-run slots remain busy after the wait budget expires."""

    def __init__(self, holder: str | None = None) -> None:
        self.holder = holder
        message = f"heavy-run slot busy: {holder}" if holder else "heavy-run slot busy"
        super().__init__(message)


def _try_lock(handle: BinaryIO) -> bool:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise
        return False


def _unlock(handle: BinaryIO) -> None:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _read_holder(slot_path: Path) -> str | None:
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        fd = os.open(slot_path, flags)
        with os.fdopen(fd, "rb") as f:
            if os.name == "nt":
                # On Windows, byte 0 is locked by the holder process, so reading byte 0
                # raises PermissionError. Seeking to 1 reads the remainder of the payload.
                f.seek(1)
            raw = f.read()
            text = raw.decode("utf-8", errors="replace").strip()
            return text or None
    except Exception:
        return None


def _resolve_slots(slots: int | None) -> int:
    if slots is not None:
        try:
            val = int(slots)
            if val < 0:
                sys.stderr.write(f"CADDIS_HEAVY_SLOTS: invalid value {slots!r}; defaulting to 1\n")
                return 1
            return val
        except (ValueError, TypeError):
            sys.stderr.write(f"CADDIS_HEAVY_SLOTS: invalid value {slots!r}; defaulting to 1\n")
            return 1

    raw = os.environ.get("CADDIS_HEAVY_SLOTS")
    if raw is None:
        return 1

    try:
        val = int(raw.strip())
        if val < 0:
            sys.stderr.write(f"CADDIS_HEAVY_SLOTS: invalid value {raw!r}; defaulting to 1\n")
            return 1
        return val
    except ValueError:
        sys.stderr.write(f"CADDIS_HEAVY_SLOTS: invalid value {raw!r}; defaulting to 1\n")
        return 1


def _resolve_wait_s(wait_s: float | None) -> float:
    if wait_s is not None:
        try:
            return max(0.0, float(wait_s))
        except (ValueError, TypeError):
            return 1200.0

    raw = os.environ.get("CADDIS_HEAVY_WAIT_S")
    if raw is None:
        return 1200.0

    try:
        return max(0.0, float(raw.strip()))
    except ValueError:
        return 1200.0


@contextlib.contextmanager
def heavy_slot(
    kind: str,
    wait_s: float | None = None,
    *,
    slots: int | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    root: Path | str | None = None,
) -> Iterator[None]:
    """Acquire an OS-level byte-locked heavy execution slot.

    Limits parallel test-heavy commands across processes and sessions.
    """
    if os.environ.get("CADDIS_HEAVY_SLOT_HELD") == "1":
        yield
        return

    num_slots = _resolve_slots(slots)
    if num_slots == 0:
        yield
        return

    timeout_s = _resolve_wait_s(wait_s)
    if root is not None:
        slot_dir = Path(root)
    else:
        # Windows %TEMP% is already per user. On POSIX /tmp is shared, and the first user to create a
        # shared folder would lock every other user out (they would see "busy" for ever), so each
        # user gets their own folder: the limit is per account, as the guide says.
        suffix = f"-{os.getuid()}" if hasattr(os, "getuid") else ""
        slot_dir = Path(tempfile.gettempdir()) / f"caddis-heavy{suffix}"
    slot_dir.mkdir(parents=True, exist_ok=True)

    deadline = clock() + timeout_s
    acquired_handle: BinaryIO | None = None
    last_holder: str | None = None

    while True:
        holders: list[str] = []
        for i in range(num_slots):
            slot_file = slot_dir / f"slot-{i}"
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
            handle = None
            try:
                fd = os.open(slot_file, flags, 0o666)
                handle = os.fdopen(fd, "r+b")
                if _try_lock(handle):
                    acquired_handle = handle
                    break
                else:
                    h = _read_holder(slot_file)
                    if h:
                        holders.append(h)
                    handle.close()
                    handle = None
            except OSError:
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
                handle = None

        if acquired_handle is not None:
            break

        if holders:
            last_holder = ", ".join(holders)

        now = clock()
        remaining = deadline - now
        if remaining <= 0:
            raise HeavySlotBusy(last_holder)

        sleep(min(2.0, remaining))

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    holder_text = f"{os.getpid()} {kind} {now_iso}"
    payload = f"\n{holder_text}\n".encode("utf-8")
    acquired_handle.seek(0)
    acquired_handle.write(payload)
    acquired_handle.truncate(len(payload))
    acquired_handle.flush()

    prev_held = os.environ.get("CADDIS_HEAVY_SLOT_HELD")
    os.environ["CADDIS_HEAVY_SLOT_HELD"] = "1"

    try:
        yield
    finally:
        if prev_held is None:
            os.environ.pop("CADDIS_HEAVY_SLOT_HELD", None)
        else:
            os.environ["CADDIS_HEAVY_SLOT_HELD"] = prev_held

        try:
            acquired_handle.seek(0)
            acquired_handle.truncate(0)
            acquired_handle.flush()
        except OSError:
            pass
        finally:
            try:
                _unlock(acquired_handle)
            finally:
                try:
                    acquired_handle.close()
                except OSError:
                    pass
