"""Temperature sweep for softmax ensemble weighting (research.md 1.1's
"Missing": a sweep across more than the one shipped point, temperature=0.05).

Reuses the exact fit/score path `fish_habitat_prediction/src/train.py`'s
`run()` uses (same spatial-block CV, same final holdout split, same seed) so
the sweep is measuring the same held-out block the shipped 0.05 result is
measured on -- not a fresh, less comparable split.

Run: PYTHONPATH=. .venv/bin/python scripts/sweep_ensemble_temperature.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fish_habitat_prediction.src import features as feature_lib
from fish_habitat_prediction.src import models as model_lib
from fish_habitat_prediction.src import pipeline
from fish_habitat_prediction.src import train as train_lib
from marine_ml import config
from marine_ml.validation import metrics, splits

TEMPERATURES = [0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.50, 1.00, 2.00]


def main() -> None:
    frame = pipeline.build(refresh_features=False)
    columns = feature_lib.feature_columns(frame)
    frame = feature_lib.drop_unusable_rows(frame, columns)
    print(f"{len(frame)} rows, {len(columns)} features, {int(frame['presence'].sum())} presences")

    fold_scores, model_scores, oof_predictions = train_lib.cross_validate(
        frame, columns, n_splits=5, block_degrees=3.0, seed=config.RANDOM_SEED
    )
    print("CV TSS per model:", {k: round(v, 4) for k, v in model_scores.items()})

    final_split = next(
        iter(
            splits.spatial_block_splits(
                frame["latitude"], frame["longitude"],
                n_splits=5, block_degrees=3.0, seed=config.RANDOM_SEED + 1,
            )
        )
    )
    train_frame = frame.iloc[final_split.train]
    test_frame = frame.iloc[final_split.test]

    niche = feature_lib.fit_thermal_niche(train_frame)
    train_fold = feature_lib.apply_thermal_niche(train_frame, niche)
    test_fold = feature_lib.apply_thermal_niche(test_frame, niche)

    predictions: dict[str, np.ndarray] = {}
    member_holdout_tss: dict[str, float] = {}
    for name, builder in model_lib.MODEL_BUILDERS.items():
        model = builder(train_fold, columns, config.RANDOM_SEED)
        model.fit(train_fold[columns], train_fold["presence"])
        scores = model.predict_proba(test_fold[columns])[:, 1]
        predictions[name] = scores
        report = metrics.evaluate_classification(
            test_fold["presence"].to_numpy(), scores, name=name, compute_boyce=True
        )
        member_holdout_tss[name] = report.as_row()["tss"]

    y_true = test_fold["presence"].to_numpy()
    best_member = max(member_holdout_tss, key=member_holdout_tss.get)
    best_member_tss = member_holdout_tss[best_member]
    print("Holdout TSS per member:", {k: round(v, 4) for k, v in member_holdout_tss.items()})
    print(f"Best single member: {best_member} @ TSS={best_member_tss:.4f}")

    rows = []
    for method in ("proportional", "softmax"):
        temps = TEMPERATURES if method == "softmax" else [None]
        for temperature in temps:
            kwargs = dict(scores=model_scores, floor=0.0, method=method)
            if temperature is not None:
                kwargs["temperature"] = temperature
            weights = model_lib.EnsembleWeights.from_scores(**kwargs)
            combined = weights.combine(predictions)
            report = metrics.evaluate_classification(
                y_true, combined, name="ensemble", compute_boyce=True
            )
            row = report.as_row()
            row["method"] = method
            row["temperature"] = temperature
            row["weights"] = str({k: round(v, 4) for k, v in weights.weights.items()})
            row["beats_best_member"] = row["tss"] > best_member_tss
            rows.append(row)

    result = pd.DataFrame(rows)
    out_path = config.REPORTS_DIR / "ensemble_temperature_sweep.csv"
    result.to_csv(out_path, index=False)
    print(f"wrote {out_path}")
    print(result[["method", "temperature", "tss", "boyce", "roc_auc", "pr_auc", "beats_best_member"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
