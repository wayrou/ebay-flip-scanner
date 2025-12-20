import re
from typing import Optional, Tuple, List


def score_listing(
    text: str,
    seller_feedback_pct: Optional[float],
    seller_feedback_score: Optional[int],
    price: float,
    est_working: Optional[float],
) -> Tuple[int, List[str]]:
    """
    Returns: (score, why_list)
    Python 3.9 compatible (uses Optional instead of `type | None`).
    """
    t = (text or "").lower()
    score = 0
    why: List[str] = []

    # "Alive" indicators (posting / booting / driver / device manager)
    if re.search(r"\bboots?\b|\bposts?\b|\bdisplays?\b|\bdisplay output\b|\bdevice manager\b|\bdriver", t):
        score += 30
        why.append("+30 alive (boots/posts/display/driver)")

    # Load / thermal / crash indicators
    if re.search(
        r"\boverheat\b|\bthermal\b|\bthermal shutdown\b|\bfurmark\b|"
        r"\bcrash(es)?\b.*\b(load|gaming|game|stress)\b|\bbsod\b|\bblue screen\b",
        t,
    ):
        score += 25
        why.append("+25 load/thermal failure language")

    # Big penalties for classic dead-card language
    if re.search(r"\bno display\b|\bno video\b|\bno signal\b|\bnot detected\b|\bdoesn'?t post\b|\bno post\b", t):
        score -= 50
        why.append("-50 no display/not detected/no post")

    # Huge penalty for corrosion/liquid
    if re.search(r"\bcorrosion\b|\brust\b|\bliquid\b|\bwater\b|\bspill\b", t):
        score -= 80
        why.append("-80 corrosion/liquid")

    # Seller trust bump (only when we actually have numbers)
    if seller_feedback_pct is not None and seller_feedback_score is not None:
        if seller_feedback_pct >= 99.0 and seller_feedback_score >= 500:
            score += 10
            why.append("+10 strong seller feedback")

    # Value bump if price looks right vs comps
    if est_working is not None and est_working > 0:
        if price <= 0.40 * est_working:
            score += 15
            why.append("+15 price <= 40% of comps")

    # Vague language penalty
    if re.search(r"\buntested\b|\bunknown\b|\bas[-\s]?is\b|\bno returns\b", t):
        score -= 20
        why.append("-20 vague/as-is language")

    return score, why