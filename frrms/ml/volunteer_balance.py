"""
Volunteer AI Balancing.

Goal: pending volunteer requests should be steered toward districts that
actually need volunteers right now -- not wherever the volunteer happened
to type in, which is how you end up with one congested district and
another with zero coverage.

need_score(district) = flood_risk_probability - congestion_penalty

congestion_penalty grows with how many volunteers are ALREADY assigned
there (diminishing returns -- the first few volunteers in a district
matter far more than the 20th), using penalty = current / (current + K).

Districts with no flood-risk data (never scored, or the model call
failed) default to a neutral 0.15 baseline risk rather than 0 -- an
unscored district should not look "safe", it should look "unknown but
plausibly still needs help", so it doesn't get starved by districts that
simply happen to have fresher weather data.
"""
from __future__ import annotations

from dataclasses import dataclass

CONGESTION_SATURATION_K = 3.0
UNKNOWN_RISK_BASELINE = 0.15


@dataclass
class PendingRequest:
    id: int
    team_name: str
    preferred_district: str | None


@dataclass
class Suggestion:
    request_id: int
    team_name: str
    preferred_district: str | None
    suggested_district: str
    suggested_need_score: float
    preferred_district_need_score: float | None
    reason: str


def _need_score(risk: float, current_count: int) -> float:
    penalty = current_count / (current_count + CONGESTION_SATURATION_K)
    return risk - penalty


def compute_assignments(
    pending: list[PendingRequest],
    district_risk: dict[str, float],
    current_counts: dict[str, int],
) -> list[Suggestion]:
    # Work on a mutable copy so assignments within this batch affect
    # subsequent suggestions (avoids piling every request onto the same
    # single "most needy" district).
    counts = dict(current_counts)
    all_districts = set(district_risk.keys()) | set(counts.keys())

    suggestions: list[Suggestion] = []
    for req in pending:
        if not all_districts:
            break

        scored = {
            d: _need_score(district_risk.get(d, UNKNOWN_RISK_BASELINE), counts.get(d, 0))
            for d in all_districts
        }
        best_district = max(scored, key=scored.get)
        best_score = scored[best_district]

        preferred_score = None
        if req.preferred_district and req.preferred_district in scored:
            preferred_score = scored[req.preferred_district]

        if req.preferred_district and req.preferred_district == best_district:
            reason = f"Preferred district matches highest need (risk {district_risk.get(best_district, UNKNOWN_RISK_BASELINE):.0%}, {counts.get(best_district, 0)} current volunteers)."
        elif req.preferred_district:
            preferred_count = counts.get(req.preferred_district, 0)
            preferred_risk = district_risk.get(req.preferred_district, UNKNOWN_RISK_BASELINE)
            best_risk = district_risk.get(best_district, UNKNOWN_RISK_BASELINE)

            if preferred_count > 0:
                reason = (
                    f"Preferred {req.preferred_district} already has {preferred_count} volunteer(s) -- "
                    f"{best_district} has higher unmet need "
                    f"(risk {best_risk:.0%}, only {counts.get(best_district, 0)} current volunteers)."
                )
            elif abs(preferred_risk - best_risk) < 0.01:
                reason = (
                    f"Preferred {req.preferred_district} and {best_district} are equally uncovered "
                    f"and equally high-risk (both {best_risk:.0%}) -- suggesting {best_district} to spread "
                    f"coverage rather than clustering volunteers in one district."
                )
            else:
                reason = (
                    f"{best_district} has higher unmet need than preferred {req.preferred_district} "
                    f"(risk {best_risk:.0%} vs {preferred_risk:.0%}, both currently uncovered)."
                )
        else:
            reason = (
                f"No preference given -- {best_district} currently has the "
                f"highest unmet need (risk {district_risk.get(best_district, UNKNOWN_RISK_BASELINE):.0%}, "
                f"{counts.get(best_district, 0)} current volunteers)."
            )

        suggestions.append(
            Suggestion(
                request_id=req.id,
                team_name=req.team_name,
                preferred_district=req.preferred_district,
                suggested_district=best_district,
                suggested_need_score=round(best_score, 3),
                preferred_district_need_score=round(preferred_score, 3) if preferred_score is not None else None,
                reason=reason,
            )
        )
        counts[best_district] = counts.get(best_district, 0) + 1

    return suggestions
