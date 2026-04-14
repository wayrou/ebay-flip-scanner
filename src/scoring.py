import re
from typing import List, Optional, Tuple

from market_profiles import get_market_profile


def _normalize_text(text: str) -> str:
    return (text or "").lower().replace("’", "'").replace("`", "'")


def _match_any(patterns, text: str) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def score_listing(
    text: str,
    seller_feedback_pct: Optional[float],
    seller_feedback_score: Optional[int],
    price: float,
    est_working: Optional[float],
    profile_key: str = "gpu",
) -> Tuple[int, List[str]]:
    """
    Returns: (score, why_list)
    Python 3.9 compatible (uses Optional instead of `type | None`).
    """
    profile = get_market_profile(profile_key)
    normalized_text = _normalize_text(text)
    score = 0
    why: List[str] = []

    no_output = profile.no_output_patterns and _match_any(profile.no_output_patterns, normalized_text)
    repair_listing = profile.repair_listing_patterns and _match_any(profile.repair_listing_patterns, normalized_text)
    issue = profile.issue_patterns and _match_any(profile.issue_patterns, normalized_text)
    alive = (not no_output) and profile.alive_patterns and _match_any(profile.alive_patterns, normalized_text)
    vague = profile.vague_patterns and _match_any(profile.vague_patterns, normalized_text)

    if alive:
        score += 30
        why.append("+30 alive language")

    if issue:
        score += 25
        why.append("+25 repair symptom language")

    if repair_listing:
        score += 15
        why.append("+15 broken/for-parts language")

    if no_output:
        score -= 20
        why.append("-20 no power/no output language")

    if profile.damage_patterns and _match_any(profile.damage_patterns, normalized_text):
        score -= 80
        why.append("-80 damage/liquid language")

    if seller_feedback_pct is not None and seller_feedback_score is not None:
        if seller_feedback_pct >= 99.0 and seller_feedback_score >= 500:
            score += 10
            why.append("+10 strong seller feedback")

    if est_working is not None and est_working > 0:
        if price <= 0.40 * est_working:
            score += 15
            why.append("+15 price <= 40% of comps")

    if vague and not repair_listing:
        score -= 20
        why.append("-20 vague listing language")

    return score, why
