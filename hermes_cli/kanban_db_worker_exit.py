"""Worker exit semantics: the ``(kind, code)`` decode and the log-trailer witness.

Split from ``kanban_db_dispatch`` (file-lines ratchet): the pure decode of a
worker's exit code, however it was observed, and the durable
``KANBAN_WORKER_EXIT_TRAILER`` reader — the witness a worker leaves in its own
log, readable whether or not the process running the sweep ever reaped it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from hermes_cli import kanban_db as _kb
from hermes_cli.kanban_db import (
    KANBAN_OWNER_LOST_EXIT_CODE,
    KANBAN_RATE_LIMIT_EXIT_CODE,
    KANBAN_TERMINAL_PROVIDER_EXIT_CODE,
)
from hermes_cli.quiet_single_query import KANBAN_WORKER_EXIT_TRAILER


def _exit_code_kind(code: int) -> tuple[str, int]:
    """``(kind, code)`` for a worker's exit code, however it was observed."""
    if code == 0:
        return ("clean_exit", 0)
    if code == KANBAN_RATE_LIMIT_EXIT_CODE:
        return ("rate_limited", code)
    if code == KANBAN_TERMINAL_PROVIDER_EXIT_CODE:
        return ("terminal_provider", code)
    if code == KANBAN_OWNER_LOST_EXIT_CODE:
        return ("owner_lost", code)
    return ("nonzero_exit", code)


_EXIT_TRAILER_RE = re.compile(
    r"^" + re.escape(KANBAN_WORKER_EXIT_TRAILER) + r"(\d+)\s*$", re.MULTILINE,
)


def _worker_log_exit_code(task_id: str, board: Optional[str] = None) -> Optional[int]:
    """Exit code from the trailer the worker CLI wrote to its own log; None when absent.

    The durable twin of the dispatch's reap registry: written by the worker itself
    (``hermes_cli.quiet_single_query.exit_single_query``), so it is there whether
    or not the process running this sweep ever reaped the worker. Last trailer
    wins — the log is append-mode across re-runs.
    """
    try:
        raw = _kb.read_worker_log(task_id, tail_bytes=4000, board=board)
    except Exception:
        return None
    matches = _EXIT_TRAILER_RE.findall(raw or "")
    return int(matches[-1]) if matches else None
