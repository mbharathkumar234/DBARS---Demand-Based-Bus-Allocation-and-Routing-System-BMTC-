from __future__ import annotations

import re

# Matches "X to Y", "X TO Y", "from X to Y", "X -> Y", "X, Y". Deliberately
# permissive about separators since SMS users won't be told the exact
# syntax up front and shouldn't need to memorize one -- but a bare "-" was
# deliberately left OUT of this list: real stop names in this dataset
# contain hyphens ("CS-Kempegowda Bus Station"), and "CS-Kempegowda Bus
# Station to Whitefield" would otherwise incorrectly split into "CS" and
# "Kempegowda Bus Station to Whitefield" at the first hyphen found, well
# before reaching the real " to " separator.
_QUERY_PATTERN = re.compile(
    r"^\s*(?:from\s+)?(?P<origin>.+?)\s*(?:\bto\b|->|,)\s*(?P<destination>.+?)\s*$",
    re.IGNORECASE,
)

MAX_SMS_REPLY_CHARS = 320  # ~2 SMS segments; enough for a real answer without being a wall of text


def parse_sms_query(text: str) -> tuple[str, str] | None:
    """Parse a free-text SMS/WhatsApp query into (origin, destination).

    Returns None if the text doesn't look like a route query at all (e.g.
    empty, or a single word with no separator) -- the caller should reply
    with usage instructions in that case rather than guessing.
    """
    if not text or not text.strip():
        return None
    match = _QUERY_PATTERN.match(text.strip())
    if not match:
        return None
    origin = match.group("origin").strip()
    destination = match.group("destination").strip()
    if not origin or not destination:
        return None
    return origin, destination


MIN_CONFIDENCE_FOR_CONFIDENT_REPLY = 0.55


def format_low_confidence_reply(query_text: str, resolved_origin: str, origin_score: float, resolved_destination: str, destination_score: float) -> str:
    """Built when stop-name resolution confidence is too low to give a
    confident-sounding answer. SMS has no visual context -- unlike the app
    UI, which shows the interpreted stop names next to the result -- so a
    low-confidence match needs to say so explicitly rather than state a
    route as fact. Shows what was understood so the user can correct it."""
    uncertain_parts = []
    if origin_score < MIN_CONFIDENCE_FOR_CONFIDENT_REPLY:
        uncertain_parts.append(f"'{resolved_origin}'")
    if destination_score < MIN_CONFIDENCE_FOR_CONFIDENT_REPLY:
        uncertain_parts.append(f"'{resolved_destination}'")
    return _truncate(
        f"Not sure I understood that stop name correctly (closest guess: "
        f"{' and '.join(uncertain_parts)}). Please reply with the exact "
        f"stop name, e.g. 'Majestic to Whitefield'."
    )


def format_sms_reply(prediction: dict, origin_query: str, destination_query: str) -> str:
    """Format a predict() result into a compact SMS-appropriate reply.

    Reuses the exact same prediction engine as the app (predictor.predict())
    -- this is not a separate, simplified answer, just a different
    presentation of the same real result. See api/sms.py.
    """
    best_match = prediction.get("best_match")
    if not best_match:
        alternatives = prediction.get("alternatives") or []
        if alternatives:
            # A result exists but predict() couldn't build a primary
            # best_match for it (shouldn't normally happen post-fix, but
            # keep this path honest rather than silently going quiet).
            first = alternatives[0]
            return _truncate(
                f"Try: {first.get('bus_chain', 'see app')} "
                f"({first.get('transfers', '?')} transfer(s)). "
                f"Reply with exact stop names for more options."
            )
        return (
            f"No route found from '{origin_query}' to '{destination_query}'. "
            f"Check spelling or try a well-known nearby stop name."
        )

    transfers = best_match.get("transfers") or 0
    distance = best_match.get("distance_km")
    distance_part = f", ~{distance:.1f}km" if isinstance(distance, (int, float)) else ""

    if transfers > 0:
        bus_chain = best_match.get("bus_chain", best_match.get("bus_number"))
        reply = (
            f"{best_match.get('matched_current_stop')} -> {best_match.get('matched_destination')}: "
            f"Take {bus_chain} ({transfers} transfer{'s' if transfers > 1 else ''}{distance_part})."
        )
    else:
        reply = (
            f"{best_match.get('matched_current_stop')} -> {best_match.get('matched_destination')}: "
            f"Take bus {best_match.get('bus_number')} (direct{distance_part})."
        )
    return _truncate(reply)


def _truncate(text: str) -> str:
    if len(text) <= MAX_SMS_REPLY_CHARS:
        return text
    return text[: MAX_SMS_REPLY_CHARS - 3] + "..."


USAGE_REPLY = (
    "BMTC Bus Finder: reply with 'FROM TO' e.g. 'Majestic to Whitefield' "
    "to get your bus."
)