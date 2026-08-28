"""Apply the shipping bar to trained horizons, and file the failures.

The bar, from TODO.md: a horizon ships only if **skill > 0 AND at most 1 of 5
folds is negative**. The second clause is the load-bearing one — six previously
rejected horizons printed `beats persistence` on the aggregate line the training
log shows, because an aggregate can read healthy over folds that include
negatives.

This exists because `train_forecasting.py` trains every *configured* horizon and
saves each one that fits. It has no concept of rejection, so a retrain silently
resurrects horizons that were deleted on their own merits — which is exactly
what a batch retrain does, and exactly what nobody would notice.

Failures are **moved to `models/forecasting/_rejected/<YYYYMMDD>/`**, never
deleted: the artifact is the evidence for the decision, and the next person to
propose retraining one should be able to read why it was dropped.

    python scripts/apply_shipping_bar.py --dry-run
    python scripts/apply_shipping_bar.py --variable nitrate
    python scripts/apply_shipping_bar.py            # every trained variable
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "models" / "forecasting"
REJECTED = ROOT / "_rejected"

MAX_NEGATIVE_FOLDS = 1


def _verdict(metrics_path: Path) -> tuple[bool, float, list[float]]:
    payload = json.loads(metrics_path.read_text())["validation"]
    skill = float(payload["metrics"]["skill_score"])
    folds = [float(f["skill_score"]) for f in payload.get("folds", [])]
    negative = sum(1 for value in folds if value < 0)
    passes = skill > 0 and negative <= MAX_NEGATIVE_FOLDS
    return passes, skill, folds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variable", help="only this variable")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    destination = REJECTED / stamp

    variables = sorted(
        directory
        for directory in ROOT.iterdir()
        if directory.is_dir() and not directory.name.startswith("_")
    )
    if args.variable:
        variables = [directory for directory in variables if directory.name == args.variable]
        if not variables:
            print(f"no trained variable named {args.variable!r}")
            return 2

    failures = 0
    for variable in variables:
        for horizon_dir in sorted(variable.iterdir(), key=lambda p: int(p.name[1:])):
            metrics_path = horizon_dir / "metrics.json"
            if not metrics_path.exists():
                continue
            passes, skill, folds = _verdict(metrics_path)
            if passes:
                continue
            failures += 1
            negative = sum(1 for value in folds if value < 0)
            print(
                f"REJECT {variable.name} {horizon_dir.name}: skill={skill:+.3f}, "
                f"{negative}/5 folds negative {[round(f, 3) for f in folds]}"
            )
            if args.dry_run:
                continue
            target = destination / variable.name / horizon_dir.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(horizon_dir), str(target))
            print(f"       -> {target.relative_to(ROOT.parent.parent)}")

    if failures == 0:
        print("every trained horizon clears the bar")
    elif args.dry_run:
        print(f"\n{failures} horizon(s) would be rejected (dry run — nothing moved)")
    else:
        print(f"\n{failures} horizon(s) moved to {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
