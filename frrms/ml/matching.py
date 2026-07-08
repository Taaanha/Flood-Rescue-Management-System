"""
Missing-Person AI Matching.

Matches "missing" victim reports against "found" victim records (rescued /
in_shelter / hospitalized) using fuzzy name matching (rapidfuzz) plus
attribute agreement bonuses (district, gender, age-range overlap) when
those fields happen to be filled in. Degrades gracefully: if age range or
gender are missing (common in a fast-moving disaster response), the score
just relies more heavily on name + district -- and the reported confidence
is explicitly capped so the UI never claims certainty it doesn't have.

This is a decision-support ranking, not an auto-merge: a coordinator
always confirms a specific match before any record is updated.
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz


@dataclass
class PersonRecord:
    victim_id: int
    full_name: str
    district: str | None
    gender: str | None
    age_min: int | None
    age_max: int | None
    status: str


@dataclass
class MatchCandidate:
    missing_victim_id: int
    missing_name: str
    found_victim_id: int
    found_name: str
    found_district: str | None
    found_status: str
    score: float
    name_similarity: float
    district_match: bool
    gender_match: bool | None  # None = unknown (one or both missing)
    age_overlap: bool | None   # None = unknown (one or both missing)
    fields_known: int          # how many of {district, gender, age} were usable
    confidence_label: str      # human-readable, honest about data completeness


def _ranges_overlap(a_min: int, a_max: int, b_min: int, b_max: int) -> bool:
    return a_min <= b_max and b_min <= a_max


def _score_pair(missing: PersonRecord, found: PersonRecord) -> MatchCandidate:
    name_sim = fuzz.token_sort_ratio(missing.full_name or "", found.full_name or "")

    district_match = bool(
        missing.district and found.district
        and missing.district.strip().lower() == found.district.strip().lower()
    )
    district_known_mismatch = bool(
        missing.district and found.district and not district_match
    )

    gender_match: bool | None = None
    if missing.gender and found.gender:
        gender_match = missing.gender.strip().lower() == found.gender.strip().lower()

    age_overlap: bool | None = None
    if missing.age_min is not None and missing.age_max is not None \
       and found.age_min is not None and found.age_max is not None:
        age_overlap = _ranges_overlap(missing.age_min, missing.age_max, found.age_min, found.age_max)

    # Composite score: name similarity is the core signal (0-100).
    # Corroborating attributes add/subtract confidence; missing attributes
    # are simply neutral (no bonus, no penalty) rather than assumed to fail.
    score = name_sim
    if district_match:
        score += 12
    elif district_known_mismatch:
        score -= 10

    if gender_match is True:
        score += 8
    elif gender_match is False:
        score -= 20  # a firm gender mismatch is a strong signal against

    if age_overlap is True:
        score += 6
    elif age_overlap is False:
        score -= 15

    score = max(0.0, min(100.0, score))

    # Count how many corroborating fields were actually usable (not None).
    fields_known = sum([
        district_match or district_known_mismatch,
        gender_match is not None,
        age_overlap is not None,
    ])

    # Never claim full certainty when supporting data is incomplete --
    # cap the *displayed* confidence based on how much corroborating
    # data was actually available, independent of the raw name score.
    if fields_known == 3:
        display_cap = 100.0
    elif fields_known == 2:
        display_cap = 90.0
    elif fields_known == 1:
        display_cap = 80.0
    else:
        display_cap = 70.0  # name similarity alone -- never call this "certain"

    display_score = min(score, display_cap)

    if display_score >= 90:
        confidence_label = "High confidence"
    elif display_score >= 70:
        confidence_label = "Likely match"
    else:
        confidence_label = "Possible match — verify manually"

    return MatchCandidate(
        missing_victim_id=missing.victim_id,
        missing_name=missing.full_name,
        found_victim_id=found.victim_id,
        found_name=found.full_name,
        found_district=found.district,
        found_status=found.status,
        score=round(display_score, 1),
        name_similarity=round(name_sim, 1),
        district_match=district_match,
        gender_match=gender_match,
        age_overlap=age_overlap,
        fields_known=fields_known,
        confidence_label=confidence_label,
    )


MIN_SCORE_THRESHOLD = 45.0
MIN_NAME_SIMILARITY_FLOOR = 55.0  # attribute agreement alone must never manufacture a match


def compute_matches(
    missing: list[PersonRecord],
    found: list[PersonRecord],
    top_k: int = 3,
) -> dict[int, list[MatchCandidate]]:
    """
    Returns {missing_victim_id: [best candidates, descending score]},
    only including candidates above MIN_SCORE_THRESHOLD AND with name
    similarity above MIN_NAME_SIMILARITY_FLOOR (district/gender/age
    agreement alone -- e.g. same district, same gender, overlapping age
    range -- is common by coincidence in a mass-casualty event and must
    never be sufficient on its own to suggest a match).
    """
    results: dict[int, list[MatchCandidate]] = {}
    for m in missing:
        scored = [_score_pair(m, f) for f in found]
        scored = [
            c for c in scored
            if c.score >= MIN_SCORE_THRESHOLD and c.name_similarity >= MIN_NAME_SIMILARITY_FLOOR
        ]
        scored.sort(key=lambda c: c.score, reverse=True)
        results[m.victim_id] = scored[:top_k]
    return results