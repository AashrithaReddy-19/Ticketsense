"""Adaptive-threshold simulation: read-only, historical-data-driven estimates
of what a proposed auto-resolution confidence threshold would have meant for
real past decisions. This never writes to a live resolution policy — the
spec is explicit that a simulation must never auto-deploy — and it never
overrides the fixed sensitive-category human-review rule from
``app.services.resolution_policy.SENSITIVE_TERMS``; it can only ever report
that rule's effect, never bypass it.
"""
from dataclasses import dataclass
from math import sqrt

from app.services.resolution_policy import SENSITIVE_TERMS

MIN_SAMPLE_SIZE = 30
MIN_AUTO_RESOLVED_AT_THRESHOLD = 5
Z_95 = 1.959963985


@dataclass(frozen=True)
class DecisionRecord:
    confidence: float
    was_auto_resolved: bool
    was_false_resolution: bool  # only meaningful when was_auto_resolved is True


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """95% Wilson score confidence interval for a binomial proportion. Chosen
    over the naive normal approximation because it stays inside [0,1] and
    remains meaningful for the very small sample sizes real historical
    resolution-outcome data on a fresh tenant will typically have."""
    if total == 0:
        raise ValueError("wilson_interval requires at least one observation")
    p_hat = successes / total
    denominator = 1 + z ** 2 / total
    center = (p_hat + z ** 2 / (2 * total)) / denominator
    margin = (z * sqrt(p_hat * (1 - p_hat) / total + z ** 2 / (4 * total ** 2))) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def is_sensitive(category: str | None, department_name: str | None) -> bool:
    haystack = f"{category or ''} {department_name or ''}".lower()
    return any(term in haystack for term in SENSITIVE_TERMS)


def simulate(records: list[DecisionRecord], proposed_threshold: float, category: str | None = None, department_name: str | None = None) -> dict:
    if not (0.0 <= proposed_threshold <= 1.0):
        raise ValueError("proposed_threshold must be between 0 and 1")

    sample_size = len(records)
    sensitive = is_sensitive(category, department_name)

    if sample_size == 0:
        return {
            "sample_size": 0, "data_sufficient": False,
            "insufficiency_reasons": ["No historical decisions with a recorded confidence score exist yet for this scope."],
            "estimated_coverage": None, "estimated_referral_rate": None,
            "historical_false_resolution_rate": None, "confidence_interval": None,
            "auto_resolved_at_threshold": 0, "sensitive_category_override": sensitive,
        }

    covered = [r for r in records if r.confidence >= proposed_threshold]
    coverage = len(covered) / sample_size
    auto_resolved_at_threshold = [r for r in covered if r.was_auto_resolved]
    k = len(auto_resolved_at_threshold)

    false_rate = None
    interval = None
    if k > 0:
        false_count = sum(1 for r in auto_resolved_at_threshold if r.was_false_resolution)
        false_rate = false_count / k
        interval = wilson_interval(false_count, k)

    insufficiency_reasons = []
    if sample_size < MIN_SAMPLE_SIZE:
        insufficiency_reasons.append(f"Only {sample_size} historical decisions have a recorded confidence score in this scope (minimum {MIN_SAMPLE_SIZE}).")
    if k < MIN_AUTO_RESOLVED_AT_THRESHOLD:
        insufficiency_reasons.append(f"Only {k} decisions would have auto-resolved at this threshold with a known outcome (minimum {MIN_AUTO_RESOLVED_AT_THRESHOLD}).")
    data_sufficient = not insufficiency_reasons
    if sensitive:
        insufficiency_reasons.append("This category/department matches a fixed sensitive-category term; human review is required regardless of this or any threshold, independent of data sufficiency.")

    return {
        "sample_size": sample_size, "data_sufficient": data_sufficient,
        "insufficiency_reasons": insufficiency_reasons,
        "estimated_coverage": round(coverage, 4), "estimated_referral_rate": round(1 - coverage, 4),
        "historical_false_resolution_rate": round(false_rate, 4) if false_rate is not None else None,
        "confidence_interval": [round(interval[0], 4), round(interval[1], 4)] if interval else None,
        "auto_resolved_at_threshold": k, "sensitive_category_override": sensitive,
    }
