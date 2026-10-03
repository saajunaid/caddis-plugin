"""Portable advisory locks and atomic UTF-8 document writes.

Callers that have an artifact root should pass ``root=``. The resolved target
must stay within that root, including when a path component is a symlink.
"""

from __future__ import annotations

import contextlib
import errno
import math
import os
from pathlib import Path
import stat
import tempfile
import time
from typing import BinaryIO, Callable, Iterator, TypeVar

_T = TypeVar("_T")

if os.name == "nt":
    import msvcrt
else:
    import fcntl


# Windows refuses os.replace, and even a stat or a read, on a file that another process has open at
# that instant, with PermissionError (WinError 5). The window is short. Measured 2026-10-03 with one
# process replacing a file in a loop: 0 of 759 replaces failed alone, and 250 of 908 failed while a second
# process called resolve() on it. POSIX has no such window, and there a PermissionError is a real,
# lasting refusal, so it is never retried.
_RETRY_DENIED = os.name == "nt"
_DENIED_RETRY_S = 5.0


def retry_denied(operation: Callable[[], _T]) -> _T:
    """Run ``operation``; on Windows retry a transient PermissionError for up to ``_DENIED_RETRY_S`` seconds."""
    deadline = time.monotonic() + _DENIED_RETRY_S
    while True:
        try:
            return operation()
        except PermissionError:
            if not _RETRY_DENIED or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _plain(path: Path) -> Path:
    """Drop the Windows extended-length prefix: ``\\\\?\\C:\\x`` and ``C:\\x`` name the same place.

    While another process is creating or replacing a path, ``Path.resolve()`` can return it in the prefixed form
    while the root resolves to the plain form, and ``is_relative_to`` then says the path escapes the root
    (measured 2026-10-03: 2 of 60 trials of two writers starting on an empty folder; CI hit it on 2026-10-02).
    """
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + text[8:])
    if text.startswith("\\\\?\\"):
        return Path(text[4:])
    return path


def _destination(path: Path, root: Path | None) -> Path:
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("destination may not contain parent traversal")
    # Resolve the parent directory, not the file: another writer may be replacing the file right now, and
    # resolving the file opens it, which can make that writer's os.replace fail. A symlink as the last
    # component is refused below.
    resolved = _plain(retry_denied(path.parent.resolve)) / path.name
    if root is not None and not resolved.is_relative_to(_plain(Path(root).resolve())):
        raise ValueError("destination escapes artifact root")
    if retry_denied(path.is_symlink):
        raise ValueError("destination may not be a symlink")
    return resolved


def _document_mode(target: Path) -> int:
    """Mode the replaced document should keep: the existing one, else what ``open()`` would give."""
    try:
        return stat.S_IMODE(retry_denied(target.stat).st_mode)
    except FileNotFoundError:
        # os.umask has no read-only form; the probe is process-wide for one line, so a file
        # another thread creates in that window gets 0o666. caddis writers are single-threaded.
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


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
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def locked_path(
    path: Path, timeout_s: float = 5.0, *, root: Path | None = None
) -> Iterator[Path]:
    """Hold a stable adjacent lock for ``path``; never remove its inode."""
    if not math.isfinite(timeout_s) or timeout_s < 0:
        raise ValueError("timeout_s must be a finite nonnegative number")
    target = _destination(path, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    if retry_denied(lock_path.is_symlink):
        raise ValueError("lock file may not be a symlink")
    # O_NOFOLLOW closes the gap between the check above and the open on POSIX.
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    deadline = time.monotonic() + timeout_s
    with os.fdopen(os.open(lock_path, flags, 0o666), "r+b") as handle:
        while not _try_lock(handle):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for lock: {lock_path}")
            time.sleep(min(0.05, remaining))
        try:
            yield target
        finally:
            _unlock(handle)


def atomic_write(path: Path, text: str, *, root: Path | None = None) -> None:
    """Atomically replace one document; hold ``locked_path`` for read/modify/write.

    A failed write or replace removes only this call's temporary file.
    """
    target = _destination(path, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # NamedTemporaryFile creates 0o600; without this every write would narrow the document.
        os.chmod(temporary, _document_mode(target))
        retry_denied(lambda: os.replace(temporary, target))
        temporary = None  # replaced: that name may now belong to another writer
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
