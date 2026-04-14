import re

from market_profiles import get_market_profile


def _normalize_text(text: str) -> str:
    return (text or "").lower().replace("’", "'").replace("`", "'")


def _match_any(patterns, text):
    return any(re.search(pattern, text) for pattern in patterns)


def classify(text: str, profile_key: str = "gpu"):
    profile = get_market_profile(profile_key)
    normalized_text = _normalize_text(text)

    if profile.accessory_reject_patterns and _match_any(profile.accessory_reject_patterns, normalized_text):
        return "RED", ["accessory_or_part_only"]

    if profile.context_patterns and not _match_any(profile.context_patterns, normalized_text):
        return "RED", ["wrong_market_context"]

    if profile.hard_reject_patterns and _match_any(profile.hard_reject_patterns, normalized_text):
        return "RED", ["hard_reject_keyword"]

    if profile.damage_patterns and _match_any(profile.damage_patterns, normalized_text):
        return "RED", ["damage_keyword"]

    no_output = profile.no_output_patterns and _match_any(profile.no_output_patterns, normalized_text)
    alive = (not no_output) and profile.alive_patterns and _match_any(profile.alive_patterns, normalized_text)
    issue = profile.issue_patterns and _match_any(profile.issue_patterns, normalized_text)
    repair_listing = profile.repair_listing_patterns and _match_any(profile.repair_listing_patterns, normalized_text)
    vague = profile.vague_patterns and _match_any(profile.vague_patterns, normalized_text)

    if alive and issue:
        return "GREEN", ["alive", "repairable_issue"]

    if issue or repair_listing or no_output:
        return "YELLOW", ["repair_signal"]

    if vague and not alive:
        return "YELLOW", ["vague_listing"]

    return "RED", ["no_repair_signal"]
