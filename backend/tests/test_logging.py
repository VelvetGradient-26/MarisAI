"""Logging configuration.

The bug these pin is the one that existed for the life of the project: two
logging libraries side by side, neither configured by the server, so every
`logger.info(...)` in 31 stdlib-logging modules was discarded before it reached
a handler. Nothing raised, nothing was missing from a response, and the log
lines existed in the source — the failure was invisible from everywhere except
the terminal it was supposed to be printing to.

That makes these tests worth more than they look: a logging test suite normally
checks formatting, but the defect here was *silence*.
"""

from __future__ import annotations

import logging

import pytest
from loguru import logger

from app.core import logging as app_logging
from app.core.logging import InterceptHandler, configure_logging, request_id_var


@pytest.fixture
def sink():
    """Capture loguru output, restoring whatever was configured afterwards."""
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level=0)
    try:
        yield records
    finally:
        logger.remove(sink_id)


@pytest.fixture(autouse=True)
def _configured():
    # `configure_logging` is idempotent, so call it rather than assuming import
    # order gave us a configured logger.
    app_logging._configured = False
    configure_logging(level="DEBUG")
    yield


def test_a_stdlib_info_record_from_a_service_module_reaches_the_sink(sink):
    """The whole defect, in one assertion.

    Measured before this module existed:

        logging.getLogger("services.forecast_tiles").isEnabledFor(INFO) -> False
        logging.getLogger().handlers -> []

    so this exact call produced nothing at all.
    """
    logging.getLogger("services.forecast_tiles").info("grid cache warmed")

    assert [record["message"] for record in sink] == ["grid cache warmed"]
    assert logging.getLogger("services.forecast_tiles").isEnabledFor(logging.INFO)


def test_the_intercepted_record_keeps_its_origin_not_the_logging_module(sink):
    """A fixed frame depth makes every routed record claim to come from
    `logging/__init__.py`, which throws away the module name that is the entire
    reason for routing them."""
    logging.getLogger("forecasting.trainer").warning("skill below persistence")

    assert sink[0]["name"] != "logging"
    assert sink[0]["function"] == "test_the_intercepted_record_keeps_its_origin_not_the_logging_module"


def test_a_traceback_survives_the_hop(sink):
    """Dropping `exc_info` turns `logger.exception(...)` into a bare one-liner
    with the traceback silently removed — which is exactly the case this backend
    needs most, since a fire-and-forget refresh that dies is otherwise invisible."""
    try:
        raise ValueError("copernicus refresh failed")
    except ValueError:
        logging.getLogger("services.copernicus_wind").exception("refresh died")

    assert sink[0]["exception"] is not None
    assert sink[0]["exception"].type is ValueError


def test_an_unknown_level_does_not_raise_out_of_a_log_call(sink):
    """A library logging at a level loguru does not know must not throw from
    inside the log call — an exception raised while logging propagates into
    whatever was being logged about."""
    logging.addLevelName(25, "NOTICE")
    logging.getLogger("some.library").log(25, "halfway between info and warning")

    assert sink[0]["message"] == "halfway between info and warning"


def test_the_request_id_rides_on_every_record(sink):
    """Bound once per request in the middleware and read at record time, so a
    log call deep inside a service picks it up without being handed it."""
    token = request_id_var.set("abc123")
    try:
        logging.getLogger("services.drift").info("composed")
        logger.info("also from loguru")
    finally:
        request_id_var.reset(token)

    assert [record["extra"]["request_id"] for record in sink] == ["abc123", "abc123"]


def test_outside_a_request_the_id_is_a_dash(sink):
    """A scheduled refresh has no request. It must still log, and must not
    inherit the id of whatever request happened to run before it."""
    logger.info("scheduled refresh")
    assert sink[0]["extra"]["request_id"] == "-"


def test_a_library_that_reconfigures_logging_cannot_undo_the_pin(sink):
    """copernicusmarine reconfigures logging when it opens a dataset, which is
    why `scripts/build_forecast_grid.py` uses a filter rather than a level. The
    same applies here: a level it resets must not bring the banner back.
    """
    noisy = logging.getLogger("copernicusmarine")
    # Exactly what the library does to us mid-run.
    noisy.setLevel(logging.DEBUG)

    noisy.info("Dataset version was not specified, the latest one was selected")
    assert sink == []

    # An actual failure from it still gets through.
    noisy.error("credentials rejected")
    assert [record["message"] for record in sink] == ["credentials rejected"]


def test_noisy_third_parties_are_pinned_regardless_of_level():
    """DEBUG has to stay usable. httpx at DEBUG logs every request header of
    every provider call, and copernicusmarine reconfigures logging when it opens
    a dataset."""
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("copernicusmarine").level == logging.WARNING


def test_configuring_twice_does_not_double_every_line(sink):
    """`main.py` configures at import and pytest imports it more than once per
    session; stacking sinks prints everything twice."""
    configure_logging(level="DEBUG")
    configure_logging(level="DEBUG")

    logging.getLogger("services.drift").info("once")
    assert len(sink) == 1


def test_secrets_cannot_leak_through_a_traceback(capsys):
    """`diagnose=True` prints the *values* of local variables in a traceback,
    and the locals in this codebase's fetch paths include Copernicus
    credentials — `_fetch` calls `open_dataset(username=..., password=...)`.

    Asserted on the rendered output rather than on a loguru internal: the
    attribute holding this is private and has already changed name between
    versions, so a test reading it would pass on a build that leaks.
    """
    # Rebind the sink to the stderr capsys has installed.
    app_logging._configured = False
    configure_logging(level="DEBUG")

    def open_dataset(*, username: str, password: str) -> None:
        raise RuntimeError("open_dataset failed")

    copernicus_password = "s3cr3t-copernicus-password"
    try:
        # Shaped like the real call in `vector_source._fetch`, deliberately:
        # diagnose annotates the names appearing in the traced source line, so
        # the credential has to be *in* the failing call for this to test
        # anything. Verified by flipping `diagnose` to True, at which the
        # assertion below fails.
        open_dataset(username="marisai", password=copernicus_password)
    except RuntimeError:
        logger.exception("provider fetch died")

    captured = capsys.readouterr().err
    # The traceback itself is present and useful...
    assert "provider fetch died" in captured
    assert "RuntimeError" in captured
    # ...but the values of the frame's locals are not.
    assert copernicus_password not in captured


def test_the_interceptor_is_installed_on_root():
    root = logging.getLogger()
    assert any(isinstance(handler, InterceptHandler) for handler in root.handlers)
    # level=0 on root, so the per-logger levels above are what filter.
    assert root.level == 0
