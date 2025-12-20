import re

GPU_CONTEXT_STRONG = [
    r"\bgeforce\b", r"\brtx\b", r"\bgtx\b",
    r"\bradeon\b", r"\brx\s?\d{3,4}\b",
    r"\bquadro\b", r"\btitan\b",
    r"\bgraphics card\b", r"\bvideo card\b",
    r"\bpcie\b", r"\bpci express\b"
]

ACCESSORY_REJECT = [
    r"\bthermal pad(s)?\b", r"\bthermal paste\b", r"\bheatsink\b",
    r"\bbackplate\b", r"\briser\b", r"\bpcie riser\b",
    r"\bwaterblock\b", r"\bfan replacement\b", r"\bmount\b",
    r"\bbracket\b", r"\bcable\b", r"\badapter\b"
]

# IMPORTANT: We do NOT hard-reject "no display" universally, because some sellers say
# "black screen after driver" (which can be salvageable). We'll treat "no display" as a big penalty in scoring,
# and rules-based GREEN will require "alive" words anyway.
VAGUE = [r"\buntested\b", r"\bas[-\s]?is\b", r"\bunknown\b", r"\bno returns\b", r"\bparts\b"]

GREEN_ALIVE = [
    r"\bboots?\b", r"\bposts?\b", r"\bdisplays?\b", r"\bdisplay output\b",
    r"\bworks in windows\b", r"\bdriver(s)? (install|installs|installed)\b",
    r"\bdevice manager\b"
]

GREEN_THERMAL = [
    r"\boverheat\w*\b", r"\bthermal\b", r"\bthermal shutdown\b",
    r"\bshuts?\s+down\b",
    r"\bcrash(es|ed|ing)?\b.*\b(load|game|gaming|stress)\b",
    r"\bfails?\b.*\bfurmark\b", r"\bfails?\b.*\bstress\b",
    r"\bfurmark\b",
    r"\bbsod\b|\bblue screen\b",
    r"\bgreen screen\b|\bblack screen after\b"
]

def _match_any(patterns, text):
    return any(re.search(p, text) for p in patterns)

def classify(text: str):
    t = text.lower()
    
        # Reject accessories immediately
    if any(re.search(p, t) for p in ACCESSORY_REJECT):
        return "RED", ["accessory_not_gpu"]

    # Must look like an actual graphics card listing (strong evidence)
    if not any(re.search(p, t) for p in GPU_CONTEXT_STRONG):
        return "RED", ["not_gpu_card_context"]

    if not _match_any(GPU_CONTEXT, t):
        return "RED", ["not_gpu_context"]

    if _match_any(HARD_REJECT, t):
        return "RED", ["hard_reject_keyword"]

    alive = _match_any(GREEN_ALIVE, t)
    thermal = _match_any(GREEN_THERMAL, t)
    vague = _match_any(VAGUE, t)

    if alive and thermal:
        return "GREEN", ["alive", "thermal_load_failure"]

    if thermal and not alive:
        return "YELLOW", ["thermal_language_no_alive_confirm"]

    if vague and not (alive or thermal):
        return "YELLOW", ["vague_listing"]

    return "YELLOW", ["default"]