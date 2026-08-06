#!/usr/bin/env python
"""Offline training CLI for the forecasting engine.

    # one variable, its configured horizons
    python scripts/train_forecasting.py --variable sea_surface_temperature

    # specific horizons
    python scripts/train_forecasting.py --variable chlorophyll_a --horizons 1 7

    # everything (long: one upstream fetch per point per variable)
    python scripts/train_forecasting.py --all

    # see what would run, and what is already trained, without fetching
    python scripts/train_forecasting.py --all --dry-run

Training is deliberately offline and never triggered by the API. A forecast
request must not be able to start a job that fetches two years of data from
twenty-four points; the endpoint serves artifacts this script wrote, and says
so when one is missing.

Run from `backend/` so the package imports resolve:

    cd backend && .venv/bin/python scripts/train_forecasting.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow `python scripts/train_forecasting.py` from the backend directory
# without requiring PYTHONPATH to be set by hand.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forecasting import ForecastingError  # noqa: E402
from forecasting.config import get_config  # noqa: E402
from forecasting.history import clear_cache  # noqa: E402
from forecasting.model_store import list_trained  # noqa: E402
from forecasting.trainer import TrainingReport, train  # noqa: E402

logger = logging.getLogger("train_forecasting")


def _git_commit() -> str | None:
    """The commit this run trained at, so a result maps back to code.

    Best-effort — no git, no problem; it is metadata, not a precondition.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def write_run_record(
    report_dir: Path,
    *,
    run_started: datetime,
    summary: list[dict[str, Any]],
    elapsed: float,
    variables: list[str],
    horizons: list[int] | None,
    failures: int,
) -> Path:
    """Write an immutable record of one training invocation.

    `training_report.json` is a *fixed* filename, so each run destroys the one
    before it — two batches back to back leave only the second, which is
    exactly what happened on 2026-08-05 and is why "did that change help?" was
    unanswerable. This writes a copy keyed by start time that nothing
    overwrites.

    Deliberately stdlib-only. Experiment tracking proper lives in
    `machine_learning/marine_ml/tracking.py`, which *reads* these directories:
    the backend must not gain an MLflow dependency, because keeping the
    modelling stack out of its import graph is a load-bearing boundary. The
    direction of the dependency is the whole design — do not invert it by
    importing a tracking client here.
    """
    run_dir = report_dir / "runs" / run_started.strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(summary, indent=2, default=str))
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "started_at": run_started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "duration_seconds": round(elapsed, 2),
                "variables": variables,
                "horizons": horizons,
                "models_trained": len([e for e in summary if "error" not in e]),
                "models_failed": failures,
                "git_commit": _git_commit(),
                "argv": sys.argv[1:],
            },
            indent=2,
            default=str,
        )
    )
    return run_dir


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # copernicusmarine logs a banner and a depth warning per fetch; at 24
    # points x 4 horizons that is several hundred lines of noise around the
    # numbers this script exists to report.
    for noisy in ("copernicusmarine", "copernicus_marine_client", "httpx", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


def _plot_diagnostics(report_dir: Path, variable: str, horizon: int, metrics: dict) -> None:
    """Render the three diagnostic plots from the stored arrays.

    The API serves this same data as JSON so the dashboard can draw it in the
    viewer's theme; these PNGs are for the offline training report, where a
    file you can open beats a payload you have to render.
    """
    diagnostics = metrics.get("validation", {}).get("diagnostics", {})
    scatter = diagnostics.get("prediction_vs_actual") or []
    histogram = diagnostics.get("error_distribution") or []
    if not scatter:
        return

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib unavailable — skipping diagnostic plots")
        return

    figure, axes = plt.subplots(1, 3, figsize=(16, 4.5))

    actual = [point["actual"] for point in scatter]
    predicted = [point["predicted"] for point in scatter]
    axes[0].scatter(actual, predicted, s=8, alpha=0.4)
    low, high = min(actual + predicted), max(actual + predicted)
    axes[0].plot([low, high], [low, high], "r--", linewidth=1)
    axes[0].set_xlabel("Actual")
    axes[0].set_ylabel("Predicted")
    axes[0].set_title(f"{variable} h{horizon}: prediction vs actual")

    residuals = [p - a for a, p in zip(actual, predicted, strict=True)]
    axes[1].scatter(range(len(residuals)), residuals, s=8, alpha=0.4)
    axes[1].axhline(0, color="r", linestyle="--", linewidth=1)
    axes[1].set_xlabel("Validation sample")
    axes[1].set_ylabel("Residual (predicted - actual)")
    axes[1].set_title("Residuals")

    if histogram:
        centres = [(b["bin_start"] + b["bin_end"]) / 2 for b in histogram]
        counts = [b["count"] for b in histogram]
        width = histogram[0]["bin_end"] - histogram[0]["bin_start"]
        axes[2].bar(centres, counts, width=width * 0.9)
        axes[2].set_xlabel("Residual")
        axes[2].set_ylabel("Count")
        axes[2].set_title("Error distribution")

    figure.tight_layout()
    output = report_dir / f"{variable}_h{horizon}_diagnostics.png"
    figure.savefig(output, dpi=110)
    plt.close(figure)
    logger.info(f"  diagnostics -> {output}")


def _format(report: TrainingReport) -> str:
    metrics = report.metrics
    if "error" in metrics:
        return f"  h{report.horizon:<3} FAILED  {metrics['error']}"

    def value(key: str, spec: str = ".4f") -> str:
        raw = metrics.get(key)
        return format(raw, spec) if isinstance(raw, (int, float)) else "n/a"

    skill = metrics.get("skill_score")
    verdict = ""
    if isinstance(skill, (int, float)):
        verdict = "  beats persistence" if skill > 0 else "  WORSE THAN PERSISTENCE"

    return (
        f"  h{report.horizon:<3} MAE={value('mae')} RMSE={value('rmse')} "
        f"R2={value('r2')} dir={value('directional_accuracy', '.3f')} "
        f"skill={value('skill_score', '+.3f')}{verdict}  "
        f"[{report.rows} rows, {report.duration_seconds:.0f}s]"
    )


async def run(args: argparse.Namespace) -> int:
    config = get_config()
    enabled = config.enabled_variables()

    if args.all:
        targets = list(enabled)
    else:
        targets = args.variable or []
        unknown = [key for key in targets if key not in enabled]
        if unknown:
            logger.error(
                f"unknown or disabled variable(s): {', '.join(unknown)}. "
                f"Configured: {', '.join(sorted(enabled))}"
            )
            return 2

    if not targets:
        logger.error("nothing to train — pass --variable <key> or --all")
        return 2

    trained = list_trained()

    if args.dry_run:
        print(f"\n{len(targets)} variable(s) would be trained:\n")
        for key in targets:
            horizons = args.horizons or config.horizons_for(key)
            existing = trained.get(key, [])
            marks = [
                f"{h}{'*' if h in existing else ''}" for h in horizons
            ]
            points = len(config.training_for(key).points)
            print(
                f"  {key:<28} horizons={','.join(marks):<16} "
                f"points={points:<3} window={config.training_for(key).history_days}d"
            )
        print("\n  * = already trained (would be overwritten)")
        print(f"\n  Estimated upstream fetches: {sum(len(config.training_for(k).points) for k in targets)}")
        return 0

    if args.clear_cache:
        removed = clear_cache()
        logger.info(f"cleared {removed} cached history file(s)")

    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    run_started = datetime.now(UTC)
    summary: list[dict[str, Any]] = []
    failures = 0

    for index, key in enumerate(targets, start=1):
        horizons = args.horizons or config.horizons_for(key)
        variable = enabled[key]
        print(f"\n[{index}/{len(targets)}] {variable.label} ({key})")
        print(f"  covariates: {', '.join(variable.covariates) or 'none'}")

        for horizon in horizons:
            if args.skip_existing and horizon in trained.get(key, []):
                print(f"  h{horizon:<3} skipped (already trained)")
                continue
            try:
                report = await train(key, horizon, config)
                print(_format(report))
                summary.append(report.as_dict())
                if report.points_skipped:
                    print(
                        f"       {len(report.points_skipped)} point(s) skipped: "
                        f"{report.points_skipped[0]['point']} "
                        f"({report.points_skipped[0]['reason'][:70]}...)"
                    )
                if args.plots and report.artifact_path:
                    metrics = json.loads(
                        (Path(report.artifact_path) / "metrics.json").read_text()
                    )
                    _plot_diagnostics(report_dir, key, horizon, metrics)
            except ForecastingError as exc:
                failures += 1
                print(f"  h{horizon:<3} FAILED  {exc}")
                summary.append(
                    {"variable": key, "horizon": horizon, "error": str(exc)}
                )
            except Exception as exc:  # noqa: BLE001 - one variable must not kill the run
                failures += 1
                logger.exception(f"unexpected failure training {key} h{horizon}")
                print(f"  h{horizon:<3} FAILED  {exc}")
                summary.append(
                    {"variable": key, "horizon": horizon, "error": str(exc)}
                )

    elapsed = time.perf_counter() - started
    report_path = report_dir / "training_report.json"
    report_path.write_text(json.dumps(summary, indent=2, default=str))

    run_dir = write_run_record(
        report_dir,
        run_started=run_started,
        summary=summary,
        elapsed=elapsed,
        variables=targets,
        horizons=args.horizons,
        failures=failures,
    )

    succeeded = len([entry for entry in summary if "error" not in entry])
    print(
        f"\n{'=' * 70}\n"
        f"  {succeeded} model(s) trained, {failures} failed, in {elapsed / 60:.1f} min\n"
        f"  report: {report_path}\n"
        f"  run:    {run_dir}\n"
        f"{'=' * 70}"
    )
    return 1 if failures and not succeeded else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train MarisAI forecasting models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--variable", "-v", action="append",
        help="variable key to train (repeatable). Omit with --all.",
    )
    parser.add_argument("--all", action="store_true", help="train every enabled variable")
    parser.add_argument(
        "--horizons", type=int, nargs="+",
        help="horizons in steps; defaults to the variable's configured horizons",
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="leave already-trained (variable, horizon) pairs alone",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what would be trained, with no network calls",
    )
    parser.add_argument(
        "--clear-cache", action="store_true",
        help="drop the cached history before training (forces fresh fetches)",
    )
    parser.add_argument(
        "--plots", action="store_true",
        help="render diagnostic PNGs alongside the JSON report",
    )
    parser.add_argument(
        "--report-dir", default="models/forecasting/_reports",
        help="where the training report and plots are written",
    )
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()
    _configure_logging(args.verbose)

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
