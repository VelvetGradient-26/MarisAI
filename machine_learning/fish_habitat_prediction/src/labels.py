"""Presence and pseudo-absence construction for the habitat model.

This module is where the credibility of the whole habitat problem is decided,
far more than the choice of classifier is.

OBIS is **presence-only**. There is no record anywhere in it that says "this
species was looked for here and was not found". So the negative class has to
be manufactured, and how it is manufactured determines what the model learns.

The naive approach — scatter random points across the ocean and call them
absences — teaches the model to separate *sampled water from unsampled water*,
because presences cluster near research institutes, ports and shipping lanes
while random points do not. The resulting map is a beautiful picture of where
marine biologists work.

The fix (approach doc 4.5) is **target-group background sampling**: draw the
background from occurrence records of the wider taxonomic group — other
ray-finned fishes, recorded by the same kinds of surveys in the same places.
Those points carry the same spatial sampling bias as the presences, so the
bias largely cancels and what remains is the environmental signal.

Presences are also spatially thinned first, so that one intensively-sampled
bay does not dominate a species' environmental profile.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from marine_ml import config


class LabelError(RuntimeError):
    """Raised when a usable presence/background set cannot be constructed."""


def thin_presences(
    presences: pd.DataFrame,
    resolution: float = config.GRID_RESOLUTION,
    period: str = "M",
    seed: int = config.RANDOM_SEED,
) -> pd.DataFrame:
    """Keep at most one presence per grid cell per time period, per species.

    Ten trawl records from one survey in one bay on one afternoon are ten
    copies of a single environmental observation. Left in, they weight that
    cell's conditions ten times over and the model reads the survey's
    itinerary as the species' preference.
    """
    if presences.empty:
        raise LabelError("no presence records to thin")

    frame = presences.copy()
    frame["_cell_lat"] = np.round(frame["latitude"] / resolution) * resolution
    frame["_cell_lon"] = np.round(frame["longitude"] / resolution) * resolution
    frame["_period"] = pd.to_datetime(frame["observation_date"]).dt.to_period(period)

    keys = ["scientific_name", "_cell_lat", "_cell_lon", "_period"]
    thinned = (
        frame.sample(frac=1.0, random_state=seed)  # random survivor, not first-seen
        .drop_duplicates(subset=keys)
        .drop(columns=["_cell_lat", "_cell_lon", "_period"])
        .reset_index(drop=True)
    )
    return thinned


def build_target_group_background(
    presences: pd.DataFrame,
    target_group: pd.DataFrame,
    scientific_name: str,
    ratio: float = 3.0,
    resolution: float = config.GRID_RESOLUTION,
    period: str = "M",
    seed: int = config.RANDOM_SEED,
) -> pd.DataFrame:
    """Background points for one species, drawn from the target group's records.

    Excludes any target-group record of the species itself — those are
    presences, not background. Also excludes the exact (cell, period) slots
    the species' own presences occupy, so a background point never contradicts
    a presence at the same place and time.

    ``ratio`` is background points per presence. More background gives a
    better-characterised environmental envelope; the standard SDM range is
    2-10x, and the class weighting in training compensates for the imbalance.
    """
    rng = np.random.default_rng(seed)

    species_presences = presences[presences["scientific_name"] == scientific_name]
    if species_presences.empty:
        raise LabelError(f"no presences for {scientific_name!r}")

    pool = target_group.copy()
    # Drop the focal species from its own background pool.
    if "scientific_name" in pool.columns:
        pool = pool[pool["scientific_name"].fillna("") != scientific_name]
    if "species" in pool.columns:
        pool = pool[pool["species"].fillna("") != scientific_name]

    if pool.empty:
        raise LabelError(
            f"target-group pool is empty after excluding {scientific_name!r}"
        )

    def slots(frame: pd.DataFrame) -> pd.Series:
        cell_lat = np.round(frame["latitude"] / resolution) * resolution
        cell_lon = np.round(frame["longitude"] / resolution) * resolution
        period_index = pd.to_datetime(frame["observation_date"]).dt.to_period(period)
        return (
            cell_lat.astype(str) + "|" + cell_lon.astype(str) + "|" + period_index.astype(str)
        )

    occupied = set(slots(species_presences))
    pool = pool.assign(_slot=slots(pool).to_numpy())
    pool = pool[~pool["_slot"].isin(occupied)]

    # One background point per (cell, period) slot — same thinning logic as
    # presences, so both classes are sampled at the same spatial granularity.
    pool = pool.sample(frac=1.0, random_state=seed).drop_duplicates(subset="_slot")

    wanted = int(len(species_presences) * ratio)
    if len(pool) == 0:
        raise LabelError(f"no background slots available for {scientific_name!r}")
    if len(pool) > wanted:
        pool = pool.iloc[rng.choice(len(pool), size=wanted, replace=False)]

    return pool.drop(columns="_slot").reset_index(drop=True)


def build_training_table(
    presences: pd.DataFrame,
    target_group: pd.DataFrame,
    species: dict[str, str] | None = None,
    ratio: float = 3.0,
    resolution: float = config.GRID_RESOLUTION,
    seed: int = config.RANDOM_SEED,
) -> pd.DataFrame:
    """Assemble the labelled presence/background table across all species.

    One row per observation with ``presence`` in {1, 0} and ``species_key``
    identifying the species. Stacking species into a single table (rather than
    training five separate models) is what makes the multi-species,
    shared-encoder framing in the doc possible: species with few records
    borrow strength from the shared environmental response.
    """
    species = species or config.TARGET_SPECIES
    thinned = thin_presences(presences, resolution=resolution, seed=seed)

    frames: list[pd.DataFrame] = []
    for species_key, scientific_name in species.items():
        species_presences = thinned[thinned["scientific_name"] == scientific_name]
        if species_presences.empty:
            continue

        background = build_target_group_background(
            thinned,
            target_group,
            scientific_name,
            ratio=ratio,
            resolution=resolution,
            seed=seed,
        )

        frames.append(
            species_presences.assign(presence=1, species_key=species_key,
                                     scientific_name=scientific_name)
        )
        frames.append(
            background.assign(presence=0, species_key=species_key,
                              scientific_name=scientific_name)
        )

    if not frames:
        raise LabelError("no species had usable presence records")

    columns = ["latitude", "longitude", "observation_date", "presence",
               "species_key", "scientific_name"]
    table = pd.concat([f[columns] for f in frames], ignore_index=True)
    return table.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def summarise(table: pd.DataFrame) -> pd.DataFrame:
    """Per-species presence/background counts — the class-balance check the
    doc's EDA plan asks for before training, not after."""
    summary = (
        table.groupby(["species_key", "presence"], observed=True)
        .size()
        .unstack(fill_value=0)
        .rename(columns={0: "background", 1: "presence"})
    )
    summary["ratio"] = summary["background"] / summary["presence"].replace(0, np.nan)
    return summary.reset_index()
