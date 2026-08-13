"""Progress reporting for an in-flight download.

Why this exists rather than a byte-counting progress bar: `POST /api/v1/download`
does all its work *before* it writes a single byte. It fetches from up to
fourteen upstream providers, merges, cleans and formats, and only then returns
the file. A browser watching `Content-Length` and the response stream would sit
at 0% for the entire wait and then jump to 100% in one frame — technically a
progress bar, informationally useless. The wait is upstream, so the progress
has to describe the upstream work.

The transport is deliberately boring. The client generates an id, sends it with
the download request, and polls `GET /api/v1/download/progress/{id}` while the
POST is still open. That keeps the download endpoint's contract exactly as it
was — same request, same streamed file, no job queue, no server-side storage of
the export (which `routers/download.py` documents as a property worth keeping).
The alternative shapes both cost more than they are worth here: SSE cannot also
deliver the binary, and a submit/poll/collect job model would mean holding a
multi-million-cell export in memory until someone comes to fetch it.

State is per-process and in-memory, matching the rest of `services/` (see
`registry.py` and `catalog.py` — this codebase's established answer to "where
does small shared state live" is a module-level dict, not the unused DB schema).
Consequences worth stating: it does not survive a restart, and behind more than
one worker the poll can land on a process that never saw the download. Both
degrade to "no progress information", which the frontend already has to handle
because the entry legitimately does not exist yet in the moment between the
client sending the request and the server registering it.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

# The ordered stages of `service.run_download`, with the share of the bar each
# one owns. The weights are not guesses: fetching is ~14 concurrent upstream
# requests against Copernicus/ERDDAP and dominates a real download so heavily
# that giving merge and format anything more would make the bar sit at 80% for
# most of the wait, which is the specific dishonesty this module exists to
# avoid. They are ratios, not promises about wall-clock time.
Stage = Literal["preparing", "fetching", "merging", "formatting", "done"]

_STAGE_WEIGHTS: dict[Stage, float] = {
    "preparing": 0.02,
    "fetching": 0.80,
    "merging": 0.10,
    "formatting": 0.08,
    "done": 0.0,
}

_STAGE_ORDER: tuple[Stage, ...] = ("preparing", "fetching", "merging", "formatting", "done")

# Entries are tiny (a few counters and a label), but a caller that abandons a
# request leaves one behind, so they expire. Comfortably longer than the
# slowest legitimate download plus the frontend's polling gap.
_TTL_SECONDS = 30 * 60

# A hard ceiling in case something pathological creates entries faster than
# they expire. Oldest-first eviction; losing a progress entry costs a progress
# bar, never a download.
_MAX_ENTRIES = 256


@dataclass
class _Entry:
    stage: Stage = "preparing"
    providers_total: int = 0
    providers_done: int = 0
    # Human-readable source names, in completion order, for the detail line.
    completed_labels: list[str] = field(default_factory=list)
    output_format: str = ""
    updated_at: float = field(default_factory=time.monotonic)
    failed: bool = False


_entries: dict[str, _Entry] = {}
_lock = threading.Lock()


def _prune_locked() -> None:
    now = time.monotonic()
    stale = [key for key, entry in _entries.items() if now - entry.updated_at > _TTL_SECONDS]
    for key in stale:
        _entries.pop(key, None)

    while len(_entries) > _MAX_ENTRIES:
        oldest = min(_entries, key=lambda key: _entries[key].updated_at)
        _entries.pop(oldest, None)


class ProgressReporter:
    """Writes one download's progress. Safe to hold across awaits.

    Every method is a no-op when the reporter carries no id, so `run_download`
    can call it unconditionally rather than guarding each site — a request
    without progress tracking is the normal case for tests and for any caller
    that does not care.
    """

    def __init__(self, request_id: str | None) -> None:
        self.request_id = request_id

    def _update(self, mutate) -> None:
        if not self.request_id:
            return
        with _lock:
            entry = _entries.get(self.request_id)
            if entry is None:
                entry = _Entry()
                _entries[self.request_id] = entry
            mutate(entry)
            entry.updated_at = time.monotonic()
            _prune_locked()

    def start(self, *, providers_total: int, output_format: str) -> None:
        def mutate(entry: _Entry) -> None:
            entry.stage = "preparing"
            entry.providers_total = providers_total
            entry.providers_done = 0
            entry.completed_labels = []
            entry.output_format = output_format
            entry.failed = False

        self._update(mutate)

    def fetching(self) -> None:
        self._update(lambda entry: setattr(entry, "stage", "fetching"))

    def provider_done(self, label: str) -> None:
        """One upstream source finished. This is the only genuinely
        fine-grained signal in the whole pipeline, which is why fetching owns
        most of the bar."""

        def mutate(entry: _Entry) -> None:
            entry.stage = "fetching"
            entry.providers_done += 1
            entry.completed_labels.append(label)

        self._update(mutate)

    def merging(self) -> None:
        self._update(lambda entry: setattr(entry, "stage", "merging"))

    def formatting(self) -> None:
        self._update(lambda entry: setattr(entry, "stage", "formatting"))

    def done(self) -> None:
        def mutate(entry: _Entry) -> None:
            entry.stage = "done"
            entry.providers_done = entry.providers_total

        self._update(mutate)

    def failed(self) -> None:
        """Marks the entry so a poll in flight when the request dies reports
        the failure instead of a bar frozen mid-way."""
        self._update(lambda entry: setattr(entry, "failed", True))

    def release(self) -> None:
        """Drop the entry. The POST response is the real completion signal, so
        holding it after that only risks a stale read on a reused id."""
        if not self.request_id:
            return
        with _lock:
            _entries.pop(self.request_id, None)


def _fraction(entry: _Entry) -> float:
    """How far through the whole pipeline this entry is, in 0..1."""
    completed = 0.0
    for stage in _STAGE_ORDER:
        if stage == entry.stage:
            break
        completed += _STAGE_WEIGHTS[stage]

    if entry.stage == "fetching" and entry.providers_total > 0:
        share = entry.providers_done / entry.providers_total
        completed += _STAGE_WEIGHTS["fetching"] * share
    elif entry.stage == "done":
        return 1.0

    return min(completed, 1.0)


def snapshot(request_id: str) -> dict[str, object] | None:
    """The current state of one download, or None if nothing is tracked.

    None is not an error: it is also what a poll sees in the window between
    the client issuing the request and the server registering it, and after
    the download completes and releases. The caller decides what to show.
    """
    with _lock:
        entry = _entries.get(request_id)
        if entry is None:
            return None
        return {
            "stage": entry.stage,
            "fraction": round(_fraction(entry), 4),
            "providers_total": entry.providers_total,
            "providers_done": entry.providers_done,
            "completed_sources": list(entry.completed_labels),
            "output_format": entry.output_format,
            "failed": entry.failed,
        }


def active_count() -> int:
    """Tracked entries. For tests and diagnostics."""
    with _lock:
        return len(_entries)


def clear() -> None:
    """Drop every entry. Tests only."""
    with _lock:
        _entries.clear()
