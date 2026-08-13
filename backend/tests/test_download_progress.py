"""Download progress reporting.

The properties worth holding here are about *honesty* and *not interfering*:
the bar must never move backwards or claim completion early, and the reporting
must be invisible to a download that nobody is watching.
"""

from __future__ import annotations

import pytest

from services.download import progress
from services.download.progress import ProgressReporter


@pytest.fixture(autouse=True)
def _clean_registry():
    progress.clear()
    yield
    progress.clear()


def test_an_untracked_id_is_not_an_error():
    """Two normal moments in every download read as untracked: before the
    server registers the request, and after it finishes and releases."""
    assert progress.snapshot("never-seen") is None


def test_a_reporter_without_an_id_records_nothing():
    """The no-id reporter is what `run_download` uses when no one is watching.
    It has to be inert — every call site in the service invokes it
    unconditionally."""
    reporter = ProgressReporter(None)
    reporter.start(providers_total=3, output_format="csv")
    reporter.fetching()
    reporter.provider_done("Copernicus")
    reporter.done()

    assert progress.active_count() == 0


def test_fraction_advances_with_each_provider_and_never_regresses():
    """Provider completion is the only fine-grained signal the pipeline has,
    so it must actually move the bar — and a bar that goes backwards is worse
    than one that does not move."""
    reporter = ProgressReporter("req")
    reporter.start(providers_total=4, output_format="csv")

    seen = [progress.snapshot("req")["fraction"]]
    reporter.fetching()
    for label in ("A", "B", "C", "D"):
        reporter.provider_done(label)
        seen.append(progress.snapshot("req")["fraction"])

    reporter.merging()
    seen.append(progress.snapshot("req")["fraction"])
    reporter.formatting()
    seen.append(progress.snapshot("req")["fraction"])
    reporter.done()
    seen.append(progress.snapshot("req")["fraction"])

    assert seen == sorted(seen), f"fraction regressed: {seen}"
    assert seen[0] == 0.0
    assert seen[-1] == 1.0


def test_only_the_final_stage_reports_complete():
    """A bar that hits 100% while the file is still being formatted teaches the
    user that 100% means 'nearly'."""
    reporter = ProgressReporter("req")
    reporter.start(providers_total=2, output_format="pdf")
    reporter.fetching()
    reporter.provider_done("A")
    reporter.provider_done("B")
    assert progress.snapshot("req")["fraction"] < 1.0

    reporter.merging()
    assert progress.snapshot("req")["fraction"] < 1.0
    reporter.formatting()
    assert progress.snapshot("req")["fraction"] < 1.0

    reporter.done()
    assert progress.snapshot("req")["fraction"] == 1.0


def test_completed_sources_are_reported_in_completion_order():
    """Providers run concurrently and land out of order; the detail line names
    what has actually arrived, not what was requested."""
    reporter = ProgressReporter("req")
    reporter.start(providers_total=3, output_format="csv")
    reporter.fetching()
    reporter.provider_done("GEBCO")
    reporter.provider_done("Copernicus Marine")

    state = progress.snapshot("req")
    assert state["completed_sources"] == ["GEBCO", "Copernicus Marine"]
    assert state["providers_done"] == 2
    assert state["providers_total"] == 3


def test_a_zero_provider_request_does_not_divide_by_zero():
    """Not reachable through the API today (a request resolves to at least one
    provider), but the fraction maths must not be one refactor away from a
    ZeroDivisionError on the response path."""
    reporter = ProgressReporter("req")
    reporter.start(providers_total=0, output_format="csv")
    reporter.fetching()
    assert 0.0 <= progress.snapshot("req")["fraction"] <= 1.0


def test_failure_is_visible_rather_than_a_frozen_bar():
    reporter = ProgressReporter("req")
    reporter.start(providers_total=2, output_format="csv")
    reporter.fetching()
    reporter.provider_done("A")
    reporter.failed()

    assert progress.snapshot("req")["failed"] is True


def test_release_drops_the_entry():
    reporter = ProgressReporter("req")
    reporter.start(providers_total=1, output_format="csv")
    assert progress.active_count() == 1

    reporter.release()
    assert progress.snapshot("req") is None
    assert progress.active_count() == 0


def test_the_registry_is_bounded():
    """An abandoned request leaves an entry behind. They expire on a TTL, but
    the hard cap is what stops a pathological caller growing the dict without
    limit between sweeps."""
    for index in range(progress._MAX_ENTRIES + 50):
        ProgressReporter(f"req-{index}").start(providers_total=1, output_format="csv")

    assert progress.active_count() <= progress._MAX_ENTRIES
