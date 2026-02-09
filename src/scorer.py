"""Score properties against a configurable weighted matrix."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.parser import Property


@dataclass
class ScoreBreakdown:
    criterion_scores: dict[str, float]  # criterion name → weighted contribution
    bonus_scores: dict[str, float]  # bonus name → points awarded
    weighted_average: float
    bonus_total: float
    final_score: float
    value_ratio: float = 0.0


    def summary(self) -> str:
        parts = []
        for name, val in self.criterion_scores.items():
            parts.append(f"{name}={val:.0f}")
        for name, val in self.bonus_scores.items():
            if val > 0:
                parts.append(f"+{name}={val:.0f}")
        return " | ".join(parts)


def load_scoring_config(path: str | Path = "config/scoring.yaml") -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def _normalize(value: float, cfg: dict) -> float:
    """Normalize a value to 0-100 based on min/max and direction."""
    lo = float(cfg["min"])
    hi = float(cfg["max"])
    direction = cfg.get("direction", "higher_is_better")

    if hi == lo:
        return 50.0

    if direction == "lower_is_better":
        score = (hi - value) / (hi - lo) * 100
    else:
        score = (value - lo) / (hi - lo) * 100

    return max(0.0, min(100.0, score))


def _normalize_threshold(value: float, cfg: dict) -> float:
    """Normalize using threshold bands: full points under threshold, linear partial, zero above."""
    full_under = float(cfg["full_points_under"])
    zero_over = float(cfg["zero_points_over"])

    if value <= full_under:
        return 100.0
    if value >= zero_over:
        return 0.0
    # Linear interpolation in the partial zone
    return (zero_over - value) / (zero_over - full_under) * 100


def _normalize_peak(value: float, cfg: dict) -> float:
    """Normalize with a peak at the ideal value, dropping off linearly on both sides."""
    ideal = float(cfg["ideal"])
    lo = float(cfg["min"])
    hi = float(cfg["max"])

    if value <= lo or value >= hi:
        return 0.0
    if value <= ideal:
        return (value - lo) / (ideal - lo) * 100
    else:
        return (hi - value) / (hi - ideal) * 100


def _get_property_value(prop: Property, criterion: str) -> float | None:
    """Get the numeric value for a criterion from a Property."""
    if criterion == "commute":
        if not prop.commute_minutes:
            return None
        return float(max(prop.commute_minutes.values()))

    mapping = {
        "lot_size_acres": prop.lot_size_acres,
        "bedrooms": prop.bedrooms,
        "bathrooms": prop.bathrooms,
    }
    val = mapping.get(criterion)
    if val is None or val == 0:
        return None
    return float(val)


def score_property(
    prop: Property,
    config: dict[str, Any] | None = None,
    config_path: str | Path = "config/scoring.yaml",
) -> ScoreBreakdown:
    """Score a property against the scoring matrix.

    Returns a ScoreBreakdown with per-criterion details, final score, and value ratio.
    """
    if config is None:
        config = load_scoring_config(config_path)

    criteria = config.get("criteria", {})
    bonuses = config.get("bonuses", {})

    criterion_scores: dict[str, float] = {}
    total_weighted = 0.0
    total_weight = 0.0

    for name, cfg in criteria.items():
        weight = float(cfg["weight"])
        value = _get_property_value(prop, name)

        if value is None:
            # Missing data: skip this criterion (don't penalize)
            continue

        scoring_type = cfg.get("scoring")
        if scoring_type == "threshold":
            normalized = _normalize_threshold(value, cfg)
        elif scoring_type == "peak":
            normalized = _normalize_peak(value, cfg)
        else:
            normalized = _normalize(value, cfg)

        criterion_scores[name] = round(normalized, 1)
        total_weighted += normalized * weight
        total_weight += weight

    weighted_avg = total_weighted / total_weight if total_weight > 0 else 0.0

    bonus_scores: dict[str, float] = {}
    bonus_total = 0.0
    bonus_mapping = {
        "has_fireplace": prop.has_fireplace,
        "has_basement": prop.has_basement,
        "has_garage": prop.has_garage,
    }

    for name, cfg in bonuses.items():
        points = float(cfg["points"])
        if bonus_mapping.get(name) is True:
            bonus_scores[name] = points
            bonus_total += points
        else:
            bonus_scores[name] = 0.0

    final = min(100.0, weighted_avg + bonus_total)

    # Value ratio: score per $100k of price
    if prop.price > 0:
        value_ratio = round(final / (prop.price / 100_000), 2)
    else:
        value_ratio = 0.0

    return ScoreBreakdown(
        criterion_scores=criterion_scores,
        bonus_scores=bonus_scores,
        weighted_average=round(weighted_avg, 1),
        bonus_total=round(bonus_total, 1),
        final_score=round(final, 1),
        value_ratio=value_ratio,
    )
