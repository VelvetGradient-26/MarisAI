"""Opt-in progress bars for the offline grid builder.

A grid build is ~35 minutes of Copernicus reads followed by ~15 minutes of cell
loop, and until now the only signal was a log line every 5,000 cells. That is
enough to confirm a run is alive and not much else — an operator watching a
50-minute job wants to see it move.

**Off by default, and that is the whole design.** The same `build_forecast_grid`
runs from `main.py`'s 12-hourly scheduler job inside the API process, where a
bar rewriting a line on stderr would interleave with request logs and be written
to whatever the server's stdout is attached to. So the bars appear only when
something explicitly turns them on, which today is
`scripts/build_forecast_grid.py` and nothing else. `enabled()` is checked at
call time rather than captured at import, since the CLI enables it after the
modules are loaded.

`mininterval` is deliberately long. tqdm redraws with a carriage return, which
is right on a terminal and turns a redirected log into a wall of `\\r` fragments
otherwise — and a background build is exactly the case where the output is a
file being tailed. One redraw every few seconds stays readable in both.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Iterator
from contextlib import nullcontext
from typing import Any, TypeVar

from tqdm.auto import tqdm

T = TypeVar("T")

# How often a bar is allowed to repaint. Long enough that a redirected log stays
# legible, short enough that a watched terminal still feels live.
_MIN_INTERVAL_SECONDS = 2.0

_enabled = False


def enable(value: bool = True) -> None:
    """Turn progress bars on for this process. Called by the CLI, not by services."""
    global _enabled
    _enabled = value


def enabled() -> bool:
    return _enabled


def track(iterable: Iterable[T], *, description: str, total: int | None = None) -> Iterator[T]:
    """`iterable`, wrapped in a progress bar when bars are enabled.

    Yields the untouched items either way, so a caller's loop body never has to
    know which mode it is in.
    """
    if not _enabled:
        yield from iterable
        return

    with tqdm(
        iterable,
        total=total,
        desc=description,
        unit="cell",
        mininterval=_MIN_INTERVAL_SECONDS,
        file=sys.stderr,
        dynamic_ncols=True,
        smoothing=0.05,
    ) as bar:
        yield from bar


def counter(*, description: str, total: int, unit: str) -> Any:
    """A manually advanced bar, for work that is not a loop over items.

    Returns a `nullcontext` when bars are off, so the call site is the same
    `with` block either way — `None` would need a guard around every `update()`.
    """
    if not _enabled:
        return nullcontext(_Silent())

    return tqdm(
        total=total,
        desc=description,
        unit=unit,
        mininterval=_MIN_INTERVAL_SECONDS,
        file=sys.stderr,
        dynamic_ncols=True,
    )


class _Silent:
    """Accepts the bar API and does nothing, so disabled callers need no branch."""

    def update(self, _n: int = 1) -> None:
        return None

    def set_postfix_str(self, _text: str) -> None:
        return None
