# Problem B — Fish Habitat / Potential Fishing Zone

Implements section 4 of the ML Technical Approach. See
[`../README.md`](../README.md) for setup, the shared architecture, and results.

```bash
cd machine_learning
PYTHONPATH=. .venv/bin/python -m fish_habitat_prediction.src.pipeline
```

## Modules

| file | role |
|---|---|
| `src/labels.py` | presence thinning + target-group pseudo-absence generation (doc 4.5) |
| `src/features.py` | fronts, prey-availability lag, thermal niche, bathymetric context (doc 4.4) |
| `src/models.py` | MaxEnt / Random Forest / LightGBM tiers + skill-weighted ensemble (doc 4.6) |
| `src/train.py` | spatial block CV, held-out block, SHAP, MESS (doc 4.7) |
| `src/pipeline.py` | entry point |

Ocean state, regridding, geometry features and the validation harness are
**not** here — they live in `marine_ml/` and are shared with the HAB problem.

## Superseded files

Two files predate this implementation and are no longer on any import path:

- `src/config.py` — replaced by `marine_ml/config.py`, which additionally
  carries the grid definition, dataset ids and credential loading. Note it
  creates directories as an import side effect, which the new config
  deliberately does not.
- `src/build_dataset.py` — a standalone precursor of the whole pipeline. Its
  ideas survive in the current code, but three things changed on the evidence:
  its random-ocean-point pseudo-absences are replaced by target-group
  background sampling (random points teach the model to find *sampled water*
  rather than good habitat), its `copernicusmarine.subset()` downloads are
  replaced by `open_dataset(service="arco-time-series")` with a server-side
  depth bound, and its region/date window moved to where OBIS labels actually
  exist.

They are left in place rather than deleted — removing them is your call. If
you keep them, be aware that a `from .config import ...` inside `src/` now
resolves to the superseded one.

The notebooks in `notebooks/` are empty placeholders apart from
`00_download_data.ipynb`; the EDA the doc describes in 4.3 is not written up
there yet.
